from collections import defaultdict, Counter
from datetime import datetime, timedelta
from statistics import mean, median
import random

# Common labels treated as the same "called into HR" event
HR_ACTIVITY_ALIASES = {
    "hr call-in",
    "hr",
    "hr meeting",
    "called to hr",
    "called into hr",
    "hr department",
}


def time_of_day_bucket(hour: int) -> str:
    """Map hour (0-23) into a coarse daily period."""
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 21:
        return "evening"
    return "night"


def day_of_week_label(dt: datetime) -> str:
    return dt.strftime("%a")  # Mon, Tue, ...


def encode_state(activity: str, day: str | None = None, time_bucket: str | None = None) -> str:
    """
    Build a Markov state. With day/time: 'Office|Mon|morning'.
    Activity-only when temporal context is missing.
    """
    activity = activity.strip()
    if day and time_bucket:
        return f"{activity}|{day}|{time_bucket}"
    return activity


def decode_state(state: str) -> tuple[str, str | None, str | None]:
    """Return (activity, day, time_bucket)."""
    parts = state.split("|")
    if len(parts) == 3:
        return parts[0], parts[1], parts[2]
    return state, None, None


def entry_to_state(entry: dict) -> str:
    """Convert a log entry dict into a Markov state string."""
    activity = str(entry.get("activity", "")).strip()
    started_at = entry.get("started_at")
    if not activity:
        return ""
    if not started_at:
        return encode_state(activity)
    try:
        dt = datetime.fromisoformat(started_at)
    except (TypeError, ValueError):
        return encode_state(activity)
    return encode_state(activity, day_of_week_label(dt), time_of_day_bucket(dt.hour))


def format_duration(minutes: float | int | None) -> str:
    if minutes is None:
        return "—"
    minutes = int(round(minutes))
    if minutes < 60:
        return f"{minutes}m"
    hours, mins = divmod(minutes, 60)
    return f"{hours}h{mins:02d}m" if mins else f"{hours}h"


class DurationTracker:
    """Average how long activities last, optionally by day and time-of-day."""

    def __init__(self):
        # key: (activity, day|None, bucket|None) -> list of minutes
        self._durations = defaultdict(list)

    def fit(self, entries: list[dict]):
        self._durations.clear()
        for entry in entries:
            activity = str(entry.get("activity", "")).strip()
            duration = entry.get("duration_min")
            if not activity or duration is None:
                continue
            try:
                minutes = float(duration)
            except (TypeError, ValueError):
                continue
            if minutes < 0:
                continue

            day = None
            bucket = None
            started_at = entry.get("started_at")
            if started_at:
                try:
                    dt = datetime.fromisoformat(started_at)
                    day = day_of_week_label(dt)
                    bucket = time_of_day_bucket(dt.hour)
                except (TypeError, ValueError):
                    pass

            self._durations[(activity, day, bucket)].append(minutes)
            self._durations[(activity, None, None)].append(minutes)
            if day:
                self._durations[(activity, day, None)].append(minutes)

    def predict(
        self,
        activity: str,
        day: str | None = None,
        time_bucket: str | None = None,
    ) -> float | None:
        """Prefer exact day+bucket, then day, then activity-wide average."""
        for key in (
            (activity, day, time_bucket),
            (activity, day, None),
            (activity, None, None),
        ):
            samples = self._durations.get(key)
            if samples:
                return sum(samples) / len(samples)
        return None


def is_hr_activity(activity: str, target: str = "HR call-in") -> bool:
    name = activity.strip().lower()
    return name == target.strip().lower() or name in HR_ACTIVITY_ALIASES


def parse_entry_datetime(entry: dict) -> datetime | None:
    started_at = entry.get("started_at")
    if not started_at:
        return None
    try:
        return datetime.fromisoformat(started_at)
    except (TypeError, ValueError):
        return None


class HRCallInAnalyzer:
    """
    Tuned for sparse HR call-in patterns:
    - gap between call-ins (days until next)
    - typical day-of-week / time-of-day
    - what usually happens just before a call-in
    """

    def __init__(self, target_activity: str = "HR call-in"):
        self.target_activity = target_activity

    def hr_events(self, entries: list[dict]) -> list[tuple[int, dict, datetime]]:
        events = []
        for index, entry in enumerate(entries):
            if not is_hr_activity(entry.get("activity", ""), self.target_activity):
                continue
            dt = parse_entry_datetime(entry)
            if dt is None:
                continue
            events.append((index, entry, dt))
        events.sort(key=lambda item: item[2])
        return events

    def analyze(self, entries: list[dict], as_of: datetime | None = None) -> dict:
        as_of = as_of or datetime.now()
        events = self.hr_events(entries)
        report = {
            "hr_count": len(events),
            "gaps_days": [],
            "avg_gap_days": None,
            "median_gap_days": None,
            "min_gap_days": None,
            "max_gap_days": None,
            "last_hr": None,
            "days_since_last": None,
            "predicted_next": None,
            "days_until_predicted": None,
            "overdue_days": None,
            "day_of_week_counts": Counter(),
            "time_bucket_counts": Counter(),
            "typical_day": None,
            "typical_time": None,
            "avg_duration_min": None,
            "leading_context": Counter(),
            "confidence": "none",
            "confidence_label": "No data",
            "confidence_detail": "Log dated HR call-ins to build an estimate.",
            "reminder": None,
            "message": "",
        }

        if not events:
            report["message"] = (
                "Log at least one HR call-in with a date/time to begin pattern tracking."
            )
            return report

        durations = []
        for index, entry, dt in events:
            report["day_of_week_counts"][day_of_week_label(dt)] += 1
            report["time_bucket_counts"][time_of_day_bucket(dt.hour)] += 1
            if entry.get("duration_min") is not None:
                try:
                    durations.append(float(entry["duration_min"]))
                except (TypeError, ValueError):
                    pass
            # What happened immediately before this HR event in the log
            if index > 0:
                prev = entries[index - 1]
                prev_name = str(prev.get("activity", "")).strip()
                if prev_name and not is_hr_activity(prev_name, self.target_activity):
                    report["leading_context"][prev_name] += 1

        if durations:
            report["avg_duration_min"] = mean(durations)

        gaps = []
        for (_, _, earlier), (_, _, later) in zip(events, events[1:]):
            gaps.append((later.date() - earlier.date()).days)
        report["gaps_days"] = gaps

        if gaps:
            report["avg_gap_days"] = mean(gaps)
            report["median_gap_days"] = median(gaps)
            report["min_gap_days"] = min(gaps)
            report["max_gap_days"] = max(gaps)

        last_index, last_entry, last_dt = events[-1]
        report["last_hr"] = last_dt
        report["days_since_last"] = (as_of.date() - last_dt.date()).days

        if report["day_of_week_counts"]:
            report["typical_day"] = report["day_of_week_counts"].most_common(1)[0][0]
        if report["time_bucket_counts"]:
            report["typical_time"] = report["time_bucket_counts"].most_common(1)[0][0]

        if gaps:
            # Median is stabler than mean for irregular HR spacing
            gap = report["median_gap_days"]
            predicted = last_dt.date() + timedelta(days=int(round(gap)))
            # If typical weekday is known, nudge forward to the next matching weekday
            # (keeps date near the gap estimate)
            if report["typical_day"]:
                predicted = self._nudge_to_weekday(predicted, report["typical_day"], within_days=3)
            report["predicted_next"] = datetime.combine(
                predicted, last_dt.time().replace(second=0, microsecond=0)
            )
            delta = (predicted - as_of.date()).days
            report["days_until_predicted"] = delta
            if delta < 0:
                report["overdue_days"] = abs(delta)
                report["message"] = (
                    f"Based on past gaps, the next HR window may already be overdue "
                    f"by about {abs(delta)} day(s)."
                )
            elif delta == 0:
                report["message"] = "Based on past gaps, today falls in the next HR window."
            else:
                report["message"] = (
                    f"Based on past gaps, the next HR call-in is estimated in about "
                    f"{delta} day(s)."
                )
        else:
            report["message"] = (
                f"Only one dated HR call-in so far ({last_dt.strftime('%Y-%m-%d')}). "
                "Add another to estimate days until the next one."
            )

        report.update(self._confidence(report))
        report["reminder"] = self._reminder(report)
        return report

    @staticmethod
    def _confidence(report: dict) -> dict:
        """Map sample size / gap stability into weak / fair / stronger."""
        hr_count = report["hr_count"]
        gaps = report["gaps_days"] or []

        if hr_count < 2:
            return {
                "confidence": "weak",
                "confidence_label": "Weak",
                "confidence_detail": "Need at least 2 dated HR call-ins for a gap estimate.",
            }

        spread = (max(gaps) - min(gaps)) if gaps else 0
        if hr_count >= 6 and spread <= 7:
            level, label = "stronger", "Stronger"
            detail = f"{hr_count} HR dates with fairly steady gaps (spread {spread}d)."
        elif hr_count >= 4:
            level, label = "fair", "Fair"
            detail = f"{hr_count} HR dates — usable pattern, still add more for stability."
        elif hr_count >= 2:
            level, label = "weak", "Weak"
            detail = f"Only {hr_count} HR dates / {len(gaps)} gap(s) — treat dates as rough."
        else:
            level, label = "weak", "Weak"
            detail = "Not enough data yet."

        if gaps and spread > 21 and level == "fair":
            detail += " Gaps vary a lot, so confidence stays modest."
            level, label = "weak", "Weak"

        return {
            "confidence": level,
            "confidence_label": label,
            "confidence_detail": detail,
        }

    @staticmethod
    def _reminder(report: dict, warn_within_days: int = 3) -> dict | None:
        """Return a reminder payload when the next HR window is near or overdue."""
        if report.get("predicted_next") is None:
            return None
        if report.get("overdue_days") is not None:
            return {
                "level": "urgent",
                "title": "HR window may be overdue",
                "text": (
                    f"Estimated next call-in looks about {report['overdue_days']} day(s) overdue. "
                    "Check in with your granddaughter / review recent notes."
                ),
            }
        days = report.get("days_until_predicted")
        if days is None:
            return None
        if days == 0:
            return {
                "level": "urgent",
                "title": "HR window is today",
                "text": "Past gaps point to today as a likely HR call-in day.",
            }
        if 0 < days <= warn_within_days:
            nxt = report["predicted_next"]
            return {
                "level": "soon",
                "title": "HR window approaching",
                "text": (
                    f"Estimated next call-in in about {days} day(s) "
                    f"({day_of_week_label(nxt)} {nxt.strftime('%Y-%m-%d')})."
                ),
            }
        return None

    @staticmethod
    def _nudge_to_weekday(base_date, weekday_label: str, within_days: int = 3):
        """Move up to `within_days` forward to land on the typical weekday if nearby."""
        # Mon=0 ... Sun=6 in strftime %a
        labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        if weekday_label not in labels:
            return base_date
        target = labels.index(weekday_label)
        for offset in range(0, within_days + 1):
            candidate = base_date + timedelta(days=offset)
            if candidate.weekday() == target:
                return candidate
        return base_date


class MarkovChainPredictor:
    """
    A flexible N-th Order Markov Chain implementation optimized for modeling 
    sequential human habits, choice records, and routine tracking.
    """
    def __init__(self, order=1):
        """
        Initializes the predictor.
        
        Parameters:
        -----------
        order : int
            The lookback window size (Markov Chain order). 
            Order=1 means the next action depends only on the current state.
            Order=2 means it depends on the sequence of the last two states.
        """
        if order < 1:
            raise ValueError("Markov Chain order must be an integer greater than or equal to 1.")
        
        self.order = order
        # Nested dictionary structure: transition_counts[history_tuple][next_state] = frequency
        self.transition_counts = defaultdict(Counter)
        # Holds the computed probabilities: transition_matrix[history_tuple][next_state] = probability
        self.transition_matrix = defaultdict(dict)
        # Set of all unique states observed during training
        self.states = set()

    def fit(self, sequence):
        """
        Trains the Markov Chain model by counting the transitions observed 
        in an empirical sequence of choices or actions.
        
        Parameters:
        -----------
        sequence : list
            A sequential list of hashable elements representing human choices (e.g., strings, ints).
        """
        if len(sequence) <= self.order:
            print("[Warning] Sequence length is too short to train an order-{} Markov Chain.".format(self.order))
            return

        self.states.update(sequence)

        # Slide a window across the sequence to populate frequency transitions
        for i in range(len(sequence) - self.order):
            # Extract historical context matching the given order size
            history = tuple(sequence[i:i + self.order])
            next_state = sequence[i + self.order]
            
            # Increment tracking frequency
            self.transition_counts[history][next_state] += 1

        # Normalize the observed frequency counts into true probabilities
        for history, next_counts in self.transition_counts.items():
            total_transitions = sum(next_counts.values())
            for state, count in next_counts.items():
                self.transition_matrix[history][state] = count / total_transitions

    def predict_distribution(self, current_history):
        """
        Retrieves the exact probability distribution for the next likely move.
        
        Parameters:
        -----------
        current_history : list or tuple
            The most recent sequence of choices. Must match the designated order length.
            
        Returns:
        --------
        dict
            A map of potential next states and their respective mathematical probabilities.
        """
        # Enforce structural integrity of the input history profile
        history_tuple = tuple(current_history[-self.order:])
        
        if len(history_tuple) < self.order:
            raise ValueError(f"History context must match or exceed the model order length ({self.order}).")

        # Handle fallback scenarios for unseen transitions or out-of-bounds user contexts
        if history_tuple not in self.transition_matrix:
            return {}

        return self.transition_matrix[history_tuple]

    def predict_next(self, current_history):
        """
        Predicts the absolute most likely next option alongside the model's confidence rating.
        
        Parameters:
        -----------
        current_history : list or tuple
            The most recent sequence of choices.
            
        Returns:
        --------
        tuple
            (predicted_state, confidence_probability) or (None, 0.0) if context is unknown.
        """
        distribution = self.predict_distribution(current_history)
        if not distribution:
            return None, 0.0
        
        # Select the choice mapping to the maximum probability value
        most_likely = max(distribution, key=distribution.get)
        confidence = distribution[most_likely]
        return most_likely, confidence

    def simulate_future(self, starting_history, steps=5):
        """
        Generates a simulation chain of future choices based on the learned transition rules.
        Uses stochastic sampling based on calculated distribution weights.
        """
        history = list(starting_history[-self.order:])
        simulated_chain = []

        for _ in range(steps):
            distribution = self.predict_distribution(history)
            if not distribution:
                break
            
            # Weighted random selection based on empirical choice probability bounds
            states, probabilities = zip(*distribution.items())
            next_step = random.choices(states, weights=probabilities, k=1)[0]
            
            simulated_chain.append(next_step)
            # Update lookback memory window
            history.append(next_step)
            history = history[-self.order:]

        return simulated_chain

# ==========================================
# Execution Demonstration & Performance Test
# ==========================================
if __name__ == "__main__":
    # Simulated multi-week routine logs for an individual's behavior profile
    # States: 'Sleep', 'Home', 'Commute', 'Office', 'Gym', 'Restaurant'
    empirical_user_logs = [
        'Sleep', 'Home', 'Commute', 'Office', 'Gym', 'Home', 'Sleep',
        'Sleep', 'Home', 'Commute', 'Office', 'Restaurant', 'Home', 'Sleep',
        'Sleep', 'Home', 'Commute', 'Office', 'Gym', 'Home', 'Sleep',
        'Sleep', 'Home', 'Commute', 'Office', 'Office', 'Home', 'Sleep',
        'Sleep', 'Home', 'Restaurant', 'Home', 'Sleep', 'Sleep', 'Home'
    ]

    print("--- Testing Order 1 Markov Chain Model (Single State Dependency) ---")
    order_1_model = MarkovChainPredictor(order=1)
    order_1_model.fit(empirical_user_logs)

    # Predict what follows after being at the 'Office'
    current_context_1 = ['Office']
    prediction_1, confidence_1 = order_1_model.predict_next(current_context_1)
    distribution_1 = order_1_model.predict_distribution(current_context_1)

    print(f"Current State: {current_context_1}")
    print(f"Probability Distribution Matrix Segment: {dict(distribution_1)}")
    print(f"Prediction: Next move is likely '{prediction_1}' with {confidence_1:.1%} confidence.\n")


    print("--- Testing Order 2 Markov Chain Model (Deeper Behavioral Sequence) ---")
    order_2_model = MarkovChainPredictor(order=2)
    order_2_model.fit(empirical_user_logs)

    # Context matters: Did the person arrive at 'Home' from 'Gym' or 'Restaurant'?
    context_a = ['Gym', 'Home']
    context_b = ['Restaurant', 'Home']

    pred_a, conf_a = order_2_model.predict_next(context_a)
    pred_b, conf_b = order_2_model.predict_next(context_b)

    print(f"Context Sequence A: {context_a} -> Predicted Next: '{pred_a}' ({conf_a:.1%} confidence)")
    print(f"Context Sequence B: {context_b} -> Predicted Next: '{pred_b}' ({conf_b:.1%} confidence)\n")


    print("--- Generating Stochastic Human Path Trajectory Simulation ---")
    starting_seed = ['Home', 'Commute']
    simulation_steps = 4
    generated_path = order_2_model.simulate_future(starting_seed, steps=simulation_steps)
    print(f"Initial State: {starting_seed}")
    print(f"Simulated Future Timeline: {generated_path}")
