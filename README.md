# portfolio-qc

Backend quality control for the public work of Scott Nelson, a Data Engineer with an M.S. in Applied Data Intelligence from SJSU.

The portfolio is [scottn66.github.io](https://scottn66.github.io). This repository is the checker for that proof of work: a small tested Python package and CI that keeps running as the pages and datasets change. The GitHub rename to `portfolio-qc` comes later.

## Goal

Continuously verify four things:

1. **Site health and links.** [scottn66.github.io](https://scottn66.github.io) stays up, and its internal pages and the public repositories it points at respond.
2. **Data checks.** Contracts on the Solar ROI inputs in [solar-energy-analysis](https://github.com/scottn66/solar-energy-analysis) and on the BTC price series published with [Does Bitcoin Follow a Power Law?](https://scottn66.github.io/bitcoin-power-law/index.html).
3. **CI.** Lint, types, tests, and a dependency audit on this package, once the package is in the tree.
4. **A claim-to-evidence table.** Each public claim mapped to a page or repository, with the date it was last checked.

## Evidence

Every link below was requested on 2026-10-28 and returned HTTP 200.

### Site

| Page | What it is |
| --- | --- |
| [scottn66.github.io](https://scottn66.github.io) | Portfolio home. The page title and JSON-LD `jobTitle` are Data Engineer. |
| [Solar viability](https://scottn66.github.io/solar/) | Rooftop solar ROI write-up. |
| [Solar reports](https://scottn66.github.io/solar/reports/) | Published solar reports. |
| [Bitcoin power law](https://scottn66.github.io/bitcoin-power-law/index.html) | BTC price series and the power-law write-up. Series file: [`bitcoin-power-law/assets/data.js`](https://github.com/scottn66/scottn66.github.io/blob/main/bitcoin-power-law/assets/data.js). |
| [Demographics](https://scottn66.github.io/demographics/) | Demographics page. |
| [Q-learning crawler](https://scottn66.github.io/Q.html) | Q-learning write-up. |
| [Robot arm, on the site](https://scottn66.github.io/robot-arm-sim/index.html) | Crawling-robot page. |
| [Wikipedia](https://scottn66.github.io/wikipedia_scraper.html), [SEP](https://scottn66.github.io/sep_scraper.html), [arXiv](https://scottn66.github.io/arxiv_scraper.html) | Knowledge-source scraper pages. |

### Repositories

Public repositories under [scottn66](https://github.com/scottn66):

| Repository | What it is |
| --- | --- |
| [solar-energy-analysis](https://github.com/scottn66/solar-energy-analysis) | Rooftop solar ROI model: NREL/NASA production, utility rates, NEM policy, and a 25-year cashflow. California in depth; Oregon included. Inputs live in [`data/`](https://github.com/scottn66/solar-energy-analysis/tree/main/data) (`eia_state_rates_2025.csv`, `nem3_acc_2025.csv`, `oregon_locations.csv`, `uszips.csv`, `utility_tou_schedules.csv`). |
| [scottn66.github.io](https://github.com/scottn66/scottn66.github.io) | Source of the public site, including the BTC series. |
| [robot-arm-sim](https://github.com/scottn66/robot-arm-sim) | Planar crawling-robot simulator. Tabular Q-learning and SARSA. |
| [wiki](https://github.com/scottn66/wiki) | Retrieval through the Wikipedia API and DBpedia. |
| [255-final-project](https://github.com/scottn66/255-final-project) | DATA 255 group project. |
| [data245-group6-project](https://github.com/scottn66/data245-group6-project) | DATA 245 term project. |
| [SURP](https://github.com/scottn66/SURP) | DSPy analysis of labeled news articles. |
| [solar](https://github.com/scottn66/solar) | Earlier notes on solar-farm ROI. |

## Roadmap

1. `uv` project: `pyproject.toml`, `uv.lock`, Python 3.12, `src/portfolio_qc/`, with pinned `httpx`, `pydantic`, `pandas`, and `pandera`.
2. pytest with coverage, failing under 80% on the new package.
3. GitHub Actions: ruff (lint and format), mypy strict, pytest with coverage, and pip-audit on `uv.lock`. Pin action SHAs. Dependabot for pip and actions.
4. gitleaks in CI and pre-commit, plus SAST (bandit or semgrep, and CodeQL).
5. Link checker for scottn66.github.io. Internal links and repository links must return 200. Nightly run, report saved as an artifact.
6. Data contracts for the Solar ROI inputs (NREL/NASA production and rates) and the BTC series: row counts, nulls, ranges, and freshness.
7. `portfolio-qc health`: the site is reachable, key pages contain the expected titles (including Data Engineer), and JSON-LD parses.
8. Structured logging: stdlib JSON formatter, run ids, and exit codes CI can use.
9. Slim multi-stage image, with a `docker run` smoke test in CI.
10. Badges, and a generated claim-to-evidence table (claim, link, last verified date).
11. Rename the GitHub repository to `portfolio-qc` and add it to the site's projects section.

## History

`ds_algo/`, `ml/`, the Stanford IMDB data, the MNIST files, the CS161 lecture PDFs, the vendored minFunc code, and the `.DS_Store` files remain in git history. The last commit that contains them is `7489ba766ce73773f05102f06cc68b44d6b14926`.

## License

MIT. See [LICENSE](LICENSE).
