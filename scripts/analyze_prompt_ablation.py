"""Use the official trace analyzer with the diagnostic task-name alias resolved."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    path = ROOT / 'vendor/Instrumental-Choices/scripts/analyze_tool_traces.py'
    spec = importlib.util.spec_from_file_location('official_trace_analyzer', path)
    assert spec is not None and spec.loader is not None
    analyzer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(analyzer)
    original = analyzer._scenario_from_log

    def scenario_from_log(log):
        name = original(log)
        return 'budget_siphon' if name == 'budget_siphon_no_sandbox' else name

    analyzer._scenario_from_log = scenario_from_log
    return analyzer.main()


if __name__ == '__main__':
    raise SystemExit(main())
