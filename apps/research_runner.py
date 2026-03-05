from __future__ import annotations

import argparse

from packages.core.config import load_config
from packages.research.optimizer import ResearchOptimizer


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/active.yaml")
    parser.add_argument("--space", default="configs/research_space.yaml")
    parser.add_argument("--samples", type=int, default=15)
    args = parser.parse_args()

    _ = load_config(args.config)
    space = load_config(args.space)
    opt = ResearchOptimizer(out_dir="configs/candidates")
    results = opt.random_search(space, samples=args.samples)
    print(f"Generated {len(results)} candidates. Top score={results[0]['score'] if results else 'n/a'}")


if __name__ == "__main__":
    main()
