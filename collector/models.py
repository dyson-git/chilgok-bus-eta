from dataclasses import dataclass


@dataclass
class ArrivalObservation:
    routeid: str
    routeno: str
    eta_min: float
