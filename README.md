# Impresso News Agencies Training Data Sampler

## Overview

This repository contains scripts and resources for sampling articles from the Impresso API based on a list of news agencies. The process involves logging the sampling progress, saving results in a structured JSON file, and using credentials for API access.

## Usage

1. **Run the script**:
   ```bash
   python sampling_articles.py
   ```

2. **Input and Output**:
   - The script reads the list of news agencies from [`all_newsagencies.txt`](./all_newsagencies.txt).
   - Logs are saved to [`sampling_log.txt`](./sampling_log.txt). **Note**: Clean this file before running the script again, as new logs will be appended.
   - Results are saved to [`newsagencies_by_article.json`](./newsagencies_by_article.json), where:
     - Each key is a news agency.
     - Each value is a list of articles containing that news agency.

3. **Configuration**:
   - File paths can be modified in [`sampling_articles.py`](./sampling_articles.py).
   - Ensure you create a `.env` file based on the template in [`.env.example`](./.env.example), but with actual login credentials.

## File Structure

- **Input Files**:
  - [`all_newsagencies.txt`](./all_newsagencies.txt): Contains the list of news agencies (one per line).
- **Output Files**:
  - [`sampling_log.txt`](./sampling_log.txt): Logs the sampling process.
  - [`newsagencies_by_article.json`](./newsagencies_by_article.json): Stores the results of the sampling process.
- **Scripts**:
  - [`sampling_articles.py`](./sampling_articles.py): Main script for sampling articles.
  - [`getting_client.py`](./getting_client.py): Handles authentication and token retrieval for the Impresso API.
- **Environment Configuration**:
  - [`.env.example`](./.env.example): Template for environment variables.
  - `.env`: Actual environment variables file (not included in the repository; create based on `.env.example`).

## Prerequisites

- Python 3.8 or higher.
- Install dependencies:
  ```bash
  pip install -r requirements.txt
  ```

## Notes

- Ensure you have valid credentials for the Impresso API. These credentials are required to generate the API token.
- The `.env` file should include:
  - `FIRST_EMAIL` and `FIRST_PASSWORD` for the first login.
  - Optionally, `SECOND_EMAIL` and `SECOND_PASSWORD` for a second login if required.

## Example Workflow

1. Add your list of news agencies to [`all_newsagencies.txt`](./all_newsagencies.txt).
2. Configure your credentials in the `.env` file.
3. Run the script:
   ```bash
   python sampling_articles.py
   ```
4. Check the logs in [`sampling_log.txt`](./sampling_log.txt) for progress.
5. View the results in [`newsagencies_by_article.json`](./newsagencies_by_article.json).

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.