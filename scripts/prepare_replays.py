"""Prepare honest scripted demos; never claim these are recorded model calls."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rate_truth.agent.replay import DIRECTORY, SUGGESTIONS
from rate_truth.settings import ROOT


def main():
    DIRECTORY.mkdir(exist_ok=True)
    plans = [
        [
            {
                "tool": "search_hotels",
                "args": {"near_metro": 1000, "checkin": "$today", "nights": 2, "limit": 2},
            }
        ],
        [
            {"tool": "search_hotels", "args": {"limit": 2}},
            {"tool": "compare_hotels", "args": {"hotel_ids": "$two", "checkin": "$today"}},
        ],
        [
            {"tool": "search_hotels", "args": {"limit": 1}},
            {"tool": "get_rates", "args": {"hotel_id": "$first", "checkin": "$today"}},
        ],
    ]
    tasks = [
        json.loads(line) for line in (ROOT / "eval/tasks_shopper.jsonl").read_text().splitlines()
    ][:10]
    for i, message in enumerate(SUGGESTIONS):
        (DIRECTORY / f"demo-{i + 1}.json").write_text(
            json.dumps(
                {
                    "provenance": "scripted_offline_demo_not_live_recording",
                    "message": message,
                    "plan": plans[i],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    for task in tasks:
        plan = []
        for tool in task["expect_tools"]:
            args = dict(task.get("args", {}).get(tool, {}))
            if tool == "search_hotels":
                # Reviewer s01 expects guests though the search schema does not accept it.
                args.pop("guests", None)
                args["limit"] = 2
            else:
                if tool == "compare_hotels":
                    args["hotel_ids"] = "$two"
                else:
                    args["hotel_id"] = "$first"
                args.setdefault("checkin", "$today")
                if args.get("guests", 2) > 2:
                    args["room"] = "family"
                if tool == "recommend_hotels":
                    args.pop("hotel_id", None)
                    args["query"] = "beach"
            plan.append({"tool": tool, "args": args})
        (DIRECTORY / f"{task['id']}.json").write_text(
            json.dumps(
                {
                    "provenance": "scripted_offline_demo_not_live_recording",
                    "message": task["ask"],
                    "plan": plan,
                },
                indent=2,
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
