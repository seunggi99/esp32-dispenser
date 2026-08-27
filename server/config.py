from dataclasses import dataclass


@dataclass
class Settings:
    expected_delta_min_g: float = 30.0
    expected_delta_max_g: float = 300.0

    stabilization_delay_s: float = 4.0
    result_wait_s: float = 10.0
    max_consecutive_failures: int = 3

    # 대조군 모드: 무게를 무시하고 장비의 "응답했다" 여부만으로 판정한다.
    # 런타임에 바뀔 수 있어야 하므로 main.py의 POST /config 로만 갱신한다.
    trust_device_report: bool = False


settings = Settings()
