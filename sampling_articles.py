import random
import time
from impresso import DateRange # type: ignore
from impresso.client import ImpressoClient # type: ignore

# Ensure local directory is importable for helper module
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import logging
import json
from typing import Callable  # added


# Configuration
INPUT_NEWSAGENCIES_FILE = "all_newsagencies.txt"
OUTPUT_JSON_FILE = "newsagencies_by_article.json"
CLIENT_REFRESH_INTERVAL_SECONDS = 27000  # 7.5 hours
CLIENT_REFRESH_HINT_INTERVAL_SECONDS = 900  # 15 minutes


def setup_logging(log_filename: str = "sampling_log.txt"):
    """
    Set up logging to a user-specified file.

    Args:
        log_filename (str): Path to the log file. Defaults to "sampling_log.txt".
    """
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)

    # Clear existing handlers
    logger.handlers.clear()

    # Create formatter
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

    # Create file handler
    file_handler = logging.FileHandler(log_filename, mode="a", encoding="utf-8")

    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    # Create console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    # Add handlers to logger
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    # Prevent duplicate logs
    logger.propagate = False

    # Get absolute path of the log file
    absolute_log_path = os.path.abspath(log_filename)
    print(f"Logging configured. Logs will be saved to: {absolute_log_path}")
    return logger


# Set up default logging
logger = setup_logging()


def sample_impresso_uids(
    client: ImpressoClient | Callable[[], ImpressoClient],
    keyword: str,
    start_date: str | None = None,
    end_date: str | None = None,
    limit_per_query: int = 20,
    max_hits: int = 20,
    delay: float = 1.0,
) -> list[str]:
    """
    Sample article UIDs from Impresso API based on a search keyword and date range.

    The `client` argument can be either an ImpressoClient instance or a callable
    returning the current client. If a callable is provided, it will be invoked
    before each API call, enabling transparent client refresh.

    Args:
        client (connect): Impresso API client or a callable that returns the client.
        keyword (str): Keyword to search for.
        start_date (str | None): Start date for filtering (YYYY-MM-DD format).
        end_date (str | None): End date for filtering (YYYY-MM-DD format).
        limit_per_query (int): Maximum number of articles per query.
        max_hits (int): Maximum number of articles to sample.
        delay (float): Delay in seconds between API requests.

    Returns:
        list[str]: List of sampled article UIDs.

    Raises:
        ValueError: If limit_per_query is not between 1 and 100.
        Exception: If API requests fail.
    """
    logger = logging.getLogger(__name__)

    def get_c() -> ImpressoClient:
        return client() if callable(client) else client  # type: ignore

    logger.info(f"Starting sampling process for keyword: '{keyword}'")
    logger.debug(
        f"Parameters: limit_per_query={limit_per_query}, max_hits={max_hits},"
        f" delay={delay}"
    )

    if not 0 < limit_per_query <= 100:
        logger.error(
            f"Invalid limit_per_query: {limit_per_query}. Must be between 1 and 100."
        )
        raise ValueError(
            f"Invalid limit_per_query: {limit_per_query}. Must be between 1 and 100."
        )

    sampled_uids = []
    found = 0

    # Step 1: Get all years with mentions of the keyword in the date range
    logger.debug("Step 1: Fetching year facets for keyword")
    if start_date or end_date:
        date_range = DateRange(start_date, end_date)
        logger.info(f"Using date range: {date_range}")
    else:
        date_range = None
        logger.info("No date range specified, using all available data.")

    try:
        year_hits = get_c().search.facet(
            "year", term=keyword, date_range=date_range, limit=200
        ).raw
    except Exception as e:
        logger.error(f"Failed to fetch year facets: {e}")
        raise

    year_buckets = year_hits.get("data", [])
    logger.debug(f"Year facets: {year_hits}")

    if not year_buckets:
        logger.warning(f"No hits found for keyword: '{keyword}'")
        return []

    sorted_year_buckets = sorted(year_buckets, key=lambda b: b.get("value"))
    logger.info(f"Found {len(sorted_year_buckets)} years mentioning '{keyword}'")
    logger.info(f"Years found: {[b.get('value') for b in sorted_year_buckets]}")

    for year_bucket in sorted_year_buckets:
        year = year_bucket.get("value")
        if not year:
            continue

        logger.debug(f"Processing year: {year}")
        date_range = DateRange(f"{year}-01-01", f"{year}-12-31")

        # Step 2: For each year, get all newspapers with hits
        logger.info(f"Step 2: Fetching newspaper facets for year {year}")
        newspapers_raw = get_c().search.facet(
            "newspaper", term=keyword, date_range=date_range, limit=200
        ).raw
        newspaper_buckets = newspapers_raw.get("data", [])
        logger.info(f"Newspaper facets for {year}: {newspapers_raw}")

        if not newspaper_buckets:
            logger.warning(f"No newspapers found for year {year}")
            continue

        logger.debug(f"Found {len(newspaper_buckets)} newspapers for year {year}")

        for paper in newspaper_buckets:
            newspaper_id = paper.get("value")
            if not newspaper_id:
                logger.warning(f"Missing newspaper ID in facet bucket: {paper}")
                continue

            logger.debug(f"Processing newspaper: {newspaper_id} for year {year}")

            try:
                logger.debug(
                    f"Searching for articles in {newspaper_id} for year {year}"
                )
                results = get_c().search.find(
                    term=keyword,
                    newspaper_id=newspaper_id,
                    date_range=date_range,
                    with_text_contents=False,
                    limit=limit_per_query,
                ).raw
                hits = results.get("data", [])
                logger.debug(
                    f"Found {len(hits)} hits for '{newspaper_id}' in {year}. Waiting"
                    f" for {delay} seconds..."
                )
                time.sleep(delay)  # Respectful delay between requests

                if hits:
                    hit = random.choice(hits)
                    uid = hit.get("uid")
                    if uid:
                        logger.debug(
                            f"Selected UID: {uid} from {newspaper_id} in {year}"
                        )
                        sampled_uids.append(uid)
                        found += 1
                        logger.info(
                            f"Progress: {found}/(max.){max_hits} articles sampled"
                        )
                        if found >= max_hits:
                            logger.info(
                                f"Reached maximum number of articles ({max_hits})"
                            )
                            return sampled_uids
                else:
                    logger.debug(f"No results for {newspaper_id} in {year}")

            except Exception as e:
                logger.error(f"Error processing '{newspaper_id}' in {year}: {e}")

    logger.info(
        f"Sampling completed. Collected {len(sampled_uids)} UIDs for keyword"
        f" '{keyword}'"
    )
    return sampled_uids


def _get_impresso_client_lazy():
    """Lazy import to avoid static import issues when running from various contexts."""
    logger = logging.getLogger(__name__)
    try:
        from getting_client import get_impresso_client
        logger.info("Successfully imported get_impresso_client from getting_client.py")
        return get_impresso_client()
    except Exception as e1:
        logger.warning(f"Failed to import from getting_client.py: {e1}")
        try:
            from getting_client import get_impresso_client 
            logger.info("Successfully imported get_impresso_client from getting_client.py")
            return get_impresso_client()
        except Exception as e2:
            logger.error(f"Failed to import from getting_client.py: {e2}")
            raise ImportError(
                "Could not import get_impresso_client from getting_client.py or getting_client.py"
            ) from e2


def run_all_newsagencies(
    file_path: str = INPUT_NEWSAGENCIES_FILE,
    out_path: str = OUTPUT_JSON_FILE,
    limit_per_query: int = 20,
    max_hits: int = 10000,
    delay: float = 1.0,
    start_date: str | None = None,
    end_date: str | None = None,
):
    """
    Iterate over news agencies listed in a text file and collect doc_ids per agency.
    Saves results incrementally into a JSON dictionary mapping agency -> [doc_ids].
    The Impresso client is recreated every 7.5 hours to avoid token expiry.
    """
    logger = logging.getLogger(__name__)

    # Load existing results if present (to resume)
    results: dict[str, list[str]] = {}
    if os.path.exists(out_path):
        try:
            with open(out_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
                if isinstance(existing, dict):
                    # Ensure str -> list[str]
                    results = {str(k): list(v) for k, v in existing.items()}
                    logger.info(f"Loaded existing results for {len(results)} agencies from {out_path}")
        except Exception as e:
            logger.warning(f"Could not load existing JSON at {out_path}: {e}")

    # Read agencies list
    if not os.path.exists(file_path):
        logger.error(f"Agencies list file not found: {file_path}")
        return
    with open(file_path, "r", encoding="utf-8") as f:
        agencies = [line.strip() for line in f if line.strip() and not line.strip().startswith("#")]

    if not agencies:
        logger.warning("No agencies found in the input file.")
        return

    logger.info(f"Starting processing of {len(agencies)} agencies from {file_path}")

    # Create initial client
    client = _get_impresso_client_lazy()
    last_refresh = time.time()
    last_hint = last_refresh

    def get_client() -> ImpressoClient:
        nonlocal client, last_refresh, last_hint
        now = time.time()
        # Periodic hint about time left till refresh
        if now - last_hint >= CLIENT_REFRESH_HINT_INTERVAL_SECONDS:
            time_left = max(0, CLIENT_REFRESH_INTERVAL_SECONDS - int(now - last_refresh))
            hrs = time_left // 3600
            mins = (time_left % 3600) // 60
            secs = time_left % 60
            logger.info(f"Time to client re-creation: {hrs}h {mins}m {secs}s")
            last_hint = now
        # Refresh client if needed
        if now - last_refresh >= CLIENT_REFRESH_INTERVAL_SECONDS:
            logger.info("Refreshing Impresso client due to token TTL")
            try:
                client = _get_impresso_client_lazy()
                logger.info("Successfully refreshed Impresso client")
            except Exception as e:
                logger.error(f"Failed to refresh Impresso client: {e}")
            last_refresh = now
        return client

    # Create initial client
    client = _get_impresso_client_lazy()
    last_refresh = time.time()
    last_hint = last_refresh

    for idx, agency in enumerate(agencies, start=1):
        # Skip if already processed
        if agency in results and isinstance(results[agency], list) and results[agency]:
            logger.info(f"Skipping agency '{agency}' (already has {len(results[agency])} doc_ids)")
            continue

        logger.info(f"[{idx}/{len(agencies)}] Processing agency: {agency}")
        try:
            doc_ids = sample_impresso_uids(
                get_client,
                keyword=agency,
                start_date=start_date,
                end_date=end_date,
                limit_per_query=limit_per_query,
                max_hits=max_hits,
                delay=delay,
            )
            results[agency] = doc_ids
            logger.info(f"Collected {len(doc_ids)} doc_ids for '{agency}'")
        except Exception as e:
            logger.error(f"Failed processing '{agency}': {e}")
            results[agency] = []

        # Persist incrementally after each agency
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            logger.info(f"Saved progress to {out_path}")
        except Exception as e:
            logger.error(f"Failed to write JSON to {out_path}: {e}")

    logger.info("All agencies processed.")


if __name__ == "__main__":
    # Batch process all agencies from file and save results incrementally
    run_all_newsagencies(
        file_path=INPUT_NEWSAGENCIES_FILE,
        out_path=OUTPUT_JSON_FILE,
        limit_per_query=20,
        max_hits=10000,
        delay=1.0,
        # Optionally constrain by dates:
        # start_date="1900-01-01",
        # end_date="2000-12-31",
    )

    print("Sampling completed.")
