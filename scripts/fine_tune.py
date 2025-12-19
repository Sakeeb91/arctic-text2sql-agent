#!/usr/bin/env python3
"""
Fine-tuning pipeline CLI (Issue #16).
"""

import argparse
import asyncio
import json
from pathlib import Path

from models.fine_tuning import get_fine_tuning_pipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fine-tuning pipeline utilities")
    parser.add_argument(
        "--export-path",
        type=str,
        default=None,
        help="Output path for exported JSONL dataset",
    )
    parser.add_argument(
        "--no-feedback",
        action="store_true",
        help="Exclude verified feedback from dataset",
    )
    parser.add_argument(
        "--max-examples",
        type=int,
        default=None,
        help="Maximum number of examples to export",
    )
    parser.add_argument(
        "--train",
        action="store_true",
        help="Run fine-tuning after exporting dataset",
    )
    parser.add_argument(
        "--model-name",
        type=str,
        default=None,
        help="Base model name for fine-tuning",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Output directory for fine-tuned model",
    )
    parser.add_argument(
        "--register-version",
        action="store_true",
        help="Register fine-tuned model version after training",
    )
    return parser.parse_args()


async def run() -> None:
    args = parse_args()
    pipeline = await get_fine_tuning_pipeline()

    export_path = await pipeline.export_dataset(
        output_path=Path(args.export_path) if args.export_path else None,
        include_feedback=not args.no_feedback,
        max_examples=args.max_examples,
    )
    print(f"Dataset exported to {export_path}")

    if args.train:
        result = await pipeline.train(
            model_name=args.model_name,
            output_dir=args.output_dir,
            register_version=args.register_version,
        )
        print(json.dumps(result, indent=2))


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
