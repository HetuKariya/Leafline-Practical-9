"""Optional load shape: ramp up, hold, spike, then ramp down.
Use with:  locust -f locustfile.py,shape.py --host http://localhost:5000
"""
from locust import LoadTestShape


class RampSpikeShape(LoadTestShape):
    # (end_time_seconds, users, spawn_rate)
    stages = [(30, 20, 5), (90, 50, 5), (120, 150, 30), (150, 50, 30), (180, 0, 10)]

    def tick(self):
        run_time = self.get_run_time()
        for end, users, rate in self.stages:
            if run_time < end:
                return users, rate
        return None
