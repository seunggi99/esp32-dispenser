#!/usr/bin/env python3
import argparse
import csv
import json
import statistics
import time
import urllib.error
import urllib.request
from pathlib import Path

FIELDNAMES = [
    "회차", "모드", "weight_before", "weight_after", "delta",
    "device_reported", "result_timeout", "verdict", "retry_count",
]

MAX_HALT_RETRIES = 5


def _http_json(method: str, url: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def set_mode(base_url: str, trust: bool) -> None:
    _http_json("POST", f"{base_url}/config", {"trust_device_report": trust})


def get_expected_range(base_url: str) -> tuple[float, float]:
    _, cfg = _http_json("GET", f"{base_url}/config")
    return cfg["expected_delta_min_g"], cfg["expected_delta_max_g"]


def resume(base_url: str, device_id: str) -> None:
    _http_json("POST", f"{base_url}/devices/{device_id}/resume")


def run_round(base_url: str, device_id: str, duration_ms: int) -> dict | None:
    for _ in range(MAX_HALT_RETRIES):
        status, body = _http_json(
            "POST", f"{base_url}/commands",
            {"device_id": device_id, "duration_ms": duration_ms},
        )
        if status == 200:
            return body
        if status == 409:
            print(f"    halted (409) -> resume 후 이 회차 재시도")
            resume(base_url, device_id)
            time.sleep(1.0)
            continue
        print(f"    명령 거부됨 ({status}): {body.get('detail')}")
        return None
    print(f"    resume 반복 실패, 이 회차 건너뜀")
    return None


def run_experiment(base_url: str, device_id: str, duration_ms: int, runs_per_mode: int, inter_run_delay: float) -> list[dict]:
    rows = []
    for mode in ("trust", "verify"):
        set_mode(base_url, trust=(mode == "trust"))
        print(f"\n=== {mode} 모드 {runs_per_mode}회 시작 ===")
        for i in range(1, runs_per_mode + 1):
            result = run_round(base_url, device_id, duration_ms)
            if result is None:
                time.sleep(inter_run_delay)
                continue

            weight_before = result.get("weight_before")
            weight_after = result.get("weight_after")
            delta = (
                weight_after - weight_before
                if weight_before is not None and weight_after is not None
                else None
            )
            row = {
                "회차": i,
                "모드": mode,
                "weight_before": weight_before,
                "weight_after": weight_after,
                "delta": delta,
                "device_reported": result.get("device_reported"),
                "result_timeout": result.get("result_timeout"),
                "verdict": result.get("verdict"),
                "retry_count": result.get("retry_count"),
            }
            rows.append(row)
            print(
                f"  [{mode} {i}/{runs_per_mode}] verdict={row['verdict']} "
                f"delta={delta} retry={row['retry_count']} timeout={row['result_timeout']}"
            )

            if result.get("halted"):
                print(f"  device {device_id} halted -> auto resume")
                resume(base_url, device_id)

            time.sleep(inter_run_delay)

    return rows


def write_csv(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def print_summary(rows: list[dict], min_g: float, max_g: float) -> None:
    print("\n=== 요약 통계 ===\n")
    print(f"기대 delta 범위: {min_g}g ~ {max_g}g\n")
    print("| 모드 | N | pass | fail | 평균 delta(g) | delta 표준편차(g) | 오판 |")
    print("|------|---|------|------|---------------|--------------------|------|")
    for mode in ("trust", "verify"):
        mode_rows = [r for r in rows if r["모드"] == mode]
        n = len(mode_rows)
        passed = sum(1 for r in mode_rows if r["verdict"] == "pass")
        failed = sum(1 for r in mode_rows if r["verdict"] == "fail")
        deltas = [r["delta"] for r in mode_rows if r["delta"] is not None]
        avg_delta = statistics.mean(deltas) if deltas else float("nan")
        std_delta = statistics.stdev(deltas) if len(deltas) > 1 else 0.0
        misjudged = sum(
            1 for r in mode_rows
            if r["verdict"] == "pass" and r["delta"] is not None and not (min_g <= r["delta"] <= max_g)
        )
        print(f"| {mode} | {n} | {passed} | {failed} | {avg_delta:.2f} | {std_delta:.2f} | {misjudged} |")
    print()


def main():
    parser = argparse.ArgumentParser(description="trust vs verify 모드 반복 대조 실험")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--duration-ms", type=int, default=3000)
    parser.add_argument("--runs-per-mode", type=int, default=20)
    parser.add_argument("--inter-run-delay", type=float, default=2.0, help="회차 사이 로드셀 안정화 대기(초)")
    parser.add_argument("--out", default=None, help="CSV 출력 경로 (기본: scripts/results_<timestamp>.csv)")
    args = parser.parse_args()

    out_path = Path(args.out) if args.out else Path(__file__).parent / f"results_{int(time.time())}.csv"

    min_g, max_g = get_expected_range(args.base_url)
    print(f"기대 delta 범위: {min_g}g ~ {max_g}g")

    rows = run_experiment(
        args.base_url, args.device_id, args.duration_ms, args.runs_per_mode, args.inter_run_delay,
    )

    write_csv(out_path, rows)
    print(f"\nCSV 저장: {out_path}")
    print_summary(rows, min_g, max_g)


if __name__ == "__main__":
    main()
