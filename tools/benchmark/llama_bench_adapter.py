#!/usr/bin/env python3
"""ComputeMesh adapter for current llama.cpp llama-bench JSON output."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import uuid
from typing import Any, Iterable

SCHEMA_VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_llama_bench_output(text: str) -> list[dict[str, Any]]:
    """Accept llama-bench JSON arrays/objects or JSONL."""
    stripped = text.strip()
    if not stripped:
        raise ValueError("llama-bench output is empty")
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        rows: list[dict[str, Any]] = []
        for lineno, line in enumerate(stripped.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid llama-bench JSONL at line {lineno}") from exc
            if not isinstance(item, dict):
                raise ValueError("llama-bench JSONL rows must be objects")
            rows.append(item)
        if not rows:
            raise ValueError("llama-bench output contains no rows")
        return rows

    if isinstance(parsed, dict):
        return [parsed]
    if isinstance(parsed, list) and all(isinstance(item, dict) for item in parsed):
        if not parsed:
            raise ValueError("llama-bench JSON array is empty")
        return parsed
    raise ValueError("llama-bench JSON must be an object, array of objects, or JSONL")


def build_command(
    executable: str,
    model_path: str,
    *,
    prompt_tokens: int,
    generated_tokens: int,
    repetitions: int,
    extra_args: Iterable[str] = (),
) -> list[str]:
    if prompt_tokens < 1 or generated_tokens < 1 or repetitions < 1:
        raise ValueError("prompt_tokens, generated_tokens, and repetitions must be >= 1")
    return [
        executable,
        "-m", model_path,
        "-p", str(prompt_tokens),
        "-n", str(generated_tokens),
        "-r", str(repetitions),
        "-o", "json",
        *extra_args,
    ]


def _row_samples(row: dict[str, Any]) -> list[dict[str, Any]]:
    ns = row.get("samples_ns") or []
    ts = row.get("samples_ts") or []
    count = max(len(ns), len(ts))
    samples: list[dict[str, Any]] = []
    for index in range(count):
        sample: dict[str, Any] = {"sample": index}
        if index < len(ns):
            sample["elapsed_ns"] = ns[index]
        if index < len(ts):
            sample["tokens_per_second"] = ts[index]
        samples.append(sample)
    return samples


def _common_metrics(row: dict[str, Any]) -> dict[str, Any]:
    filename = row.get("model_filename")
    model_name = Path(filename).name if isinstance(filename, str) and filename else None
    return {
        "llama_build_commit": row.get("build_commit"),
        "llama_build_number": row.get("build_number"),
        "backend": row.get("backends"),
        "model_name": model_name,
        "model_type": row.get("model_type"),
        "model_size_bytes": row.get("model_size"),
        "model_parameters": row.get("model_n_params"),
        "gpu_layers": row.get("n_gpu_layers"),
        "batch_size": row.get("n_batch"),
        "ubatch_size": row.get("n_ubatch"),
        "threads": row.get("n_threads"),
    }


def convert_rows(
    rows: list[dict[str, Any]],
    *,
    profile_revision: int,
    captured_at: str | None = None,
) -> list[dict[str, Any]]:
    if profile_revision < 0:
        raise ValueError("profile_revision must be >= 0")
    pp_rows = [r for r in rows if int(r.get("n_prompt") or 0) > 0 and int(r.get("n_gen") or 0) == 0]
    tg_rows = [r for r in rows if int(r.get("n_prompt") or 0) == 0 and int(r.get("n_gen") or 0) > 0]
    if len(pp_rows) != 1 or len(tg_rows) != 1:
        raise ValueError(
            f"expected exactly one prompt-processing row and one generation row; got pp={len(pp_rows)}, tg={len(tg_rows)}"
        )

    timestamp = captured_at or utc_now()
    results: list[dict[str, Any]] = []
    for phase, row in (("prefill", pp_rows[0]), ("decode", tg_rows[0])):
        avg_ns = row.get("avg_ns")
        avg_ts = row.get("avg_ts")
        if not isinstance(avg_ns, (int, float)) or avg_ns <= 0:
            raise ValueError(f"{phase} row missing positive avg_ns")
        if not isinstance(avg_ts, (int, float)) or avg_ts <= 0:
            raise ValueError(f"{phase} row missing positive avg_ts")

        metrics = _common_metrics(row)
        if phase == "prefill":
            token_count = int(row["n_prompt"])
            metrics.update({
                "prompt_tokens": token_count,
                "prefill_elapsed_ms_avg": round(float(avg_ns) / 1_000_000.0, 6),
                "prefill_tokens_per_second_avg": round(float(avg_ts), 6),
                "prefill_tokens_per_second_stddev": round(float(row.get("stddev_ts") or 0.0), 6),
            })
            benchmark_name = "llama_cpp_prefill"
        else:
            token_count = int(row["n_gen"])
            metrics.update({
                "generated_tokens": token_count,
                "decode_elapsed_ms_avg": round(float(avg_ns) / 1_000_000.0, 6),
                "decode_tokens_per_second_avg": round(float(avg_ts), 6),
                "inter_token_ms_avg": round((float(avg_ns) / token_count) / 1_000_000.0, 6),
                "decode_tokens_per_second_stddev": round(float(row.get("stddev_ts") or 0.0), 6),
            })
            benchmark_name = "llama_cpp_decode"

        metrics = {
            key: value
            for key, value in metrics.items()
            if value is None or isinstance(value, (str, int, float, bool))
        }
        results.append({
            "schema_version": SCHEMA_VERSION,
            "run_id": str(uuid.uuid4()),
            "benchmark_name": benchmark_name,
            "captured_at": timestamp,
            "profile_revision": profile_revision,
            "conditions": {
                "warm_state": "warm",
                "notes": "llama.cpp llama-bench JSON adapter; sampling is not included in llama-bench timing",
            },
            "metrics": metrics,
            "raw_samples": _row_samples(row),
        })
    return results


def run_llama_bench(
    executable: str,
    model_path: str,
    *,
    profile_revision: int,
    prompt_tokens: int = 512,
    generated_tokens: int = 128,
    repetitions: int = 5,
    extra_args: Iterable[str] = (),
    timeout: float = 900.0,
) -> list[dict[str, Any]]:
    resolved = shutil.which(executable) if not Path(executable).exists() else executable
    if not resolved:
        raise FileNotFoundError(f"llama-bench executable not found: {executable}")
    if not Path(model_path).is_file():
        raise FileNotFoundError(f"model file not found: {model_path}")
    command = build_command(
        str(resolved),
        model_path,
        prompt_tokens=prompt_tokens,
        generated_tokens=generated_tokens,
        repetitions=repetitions,
        extra_args=extra_args,
    )
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return convert_rows(parse_llama_bench_output(completed.stdout), profile_revision=profile_revision)


def write_results(output_dir: Path, results: list[dict[str, Any]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for result in results:
        path = output_dir / f"benchmark_{result['run_id']}.json"
        path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Adapt llama.cpp llama-bench output into ComputeMesh benchmark records"
    )
    parser.add_argument("--llama-bench", default="llama-bench")
    parser.add_argument("--model")
    parser.add_argument("--profile-revision", type=int, default=0)
    parser.add_argument("--prompt-tokens", type=int, default=512)
    parser.add_argument("--generated-tokens", type=int, default=128)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--extra-arg", action="append", default=[])
    parser.add_argument("--parse-file", help="Parse existing llama-bench JSON/JSONL instead of executing")
    parser.add_argument("--output-dir", default="artifacts/benchmark")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    if args.parse_file:
        text = Path(args.parse_file).read_text(encoding="utf-8")
        results = convert_rows(parse_llama_bench_output(text), profile_revision=args.profile_revision)
    else:
        if not args.model:
            parser.error("--model is required unless --parse-file is used")
        results = run_llama_bench(
            args.llama_bench,
            args.model,
            profile_revision=args.profile_revision,
            prompt_tokens=args.prompt_tokens,
            generated_tokens=args.generated_tokens,
            repetitions=args.repetitions,
            extra_args=args.extra_arg,
            timeout=args.timeout,
        )

    if args.dry_run:
        print(json.dumps(results, indent=2, sort_keys=True))
    else:
        write_results(Path(args.output_dir), results)
        print(Path(args.output_dir).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
