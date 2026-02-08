#!/usr/bin/env python3
"""
Batch Time Import Script

This script processes time tracking data from .txt files and imports them into the Common Compass system.
The input file format should be tab-separated with at least the following columns:
日期, 开始时间, 结束时间, 分钟数, 维度, 活动描述

If there are more than 6 columns, the extra columns will be merged into the description field with comma separation.

Example:
2025-08-08	12:20	12:25	5	5-财富	记录日志
2024-07-25	10:10	10:50	40	5-财富	设定年度目标并拆解到本月本周	精力管理
"""

import json
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

import requests
from pydantic import BaseModel, Field, ValidationError

# Import authentication utilities
from utils.api_auth import load_env_from_root, login_with_env

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('batch_import.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class TimeEntry(BaseModel):
    """Data model for a single time entry from the input file"""
    date: str = Field(..., description="Date in YYYY-MM-DD format")
    start_time: str = Field(..., description="Start time in HH:MM format")
    end_time: str = Field(..., description="End time in HH:MM format")
    duration_minutes: int = Field(..., description="Duration in minutes")
    dimension: str = Field(..., description="Life dimension category")
    description: str = Field(..., description="Activity description")


class ProcessedTimeEntry(BaseModel):
    """Processed time entry ready for API submission"""
    title: str = Field(..., description="Activity title")
    start_time: datetime = Field(..., description="Start datetime")
    end_time: datetime = Field(..., description="End datetime")
    dimension_id: Optional[UUID] = Field(None, description="Dimension ID")
    tracking_method: str = Field("batch_import", description="Tracking method")
    location: Optional[str] = Field(None, description="Where this activity took place")
    energy_level: Optional[int] = Field(None, ge=1, le=5, description="Energy level during activity (1-5)")
    notes: Optional[str] = Field(None, description="Additional notes")
    tags: Optional[List[str]] = Field(None, description="Activity tags")
    extra_data: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")
    task_id: Optional[UUID] = Field(None, description="Associated task ID")
    person_ids: Optional[List[str]] = Field(None, description="List of person IDs to associate with this activity")


class BatchTimeImporter:
    """Main class for batch importing time tracking data"""

    def __init__(self, api_base_url: str = "http://localhost:8000", use_auth: bool = True):
        """
        Initialize the batch importer

        Args:
            api_base_url: Base URL for the Common Compass API
            use_auth: Whether to use authentication (default: True)
        """
        self.api_base_url = api_base_url.rstrip('/')
        self.use_auth = use_auth
        self.session = None
        self.access_token = None

        # Initialize authentication if enabled
        if self.use_auth:
            try:
                load_env_from_root()
                self.session, self.api_base_url, self.access_token = login_with_env()
                logger.info(f"Successfully authenticated with API at {self.api_base_url}")

                # Verify authentication by making a test request
                if not self._verify_authentication():
                    logger.error("Authentication verification failed!")
                    logger.error("Please check your API credentials in .env file")
                    raise RuntimeError("Authentication verification failed")

                logger.info("✅ Authentication verified successfully")

            except ValueError as e:
                logger.error(f"Authentication configuration error: {e}")
                logger.error("Please ensure API_BASE_URL, API_EMAIL, and API_PASSWORD are set in .env file")
                raise
            except Exception as e:
                logger.error(f"Authentication failed: {e}")
                logger.error("Cannot continue without proper authentication")
                raise RuntimeError(f"Authentication failed: {e}")
        else:
            logger.info("Authentication disabled - using unauthenticated requests")
            self.session = requests.Session()

        self.dimension_mapping = self._load_dimension_mapping()

    def is_authenticated(self) -> bool:
        """
        Check if the importer is authenticated

        Returns:
            True if authenticated, False otherwise
        """
        return self.access_token is not None

    def _verify_authentication(self) -> bool:
        """
        Verify authentication by making a test request to the API

        Returns:
            True if authentication is working, False otherwise
        """
        try:
            response = self.session.get(f"{self.api_base_url}/api/v1/dimensions/")
            if response.status_code == 200:
                logger.info("Authentication verification successful")
                return True
            elif response.status_code == 403:
                logger.error("Authentication verification failed: 403 Forbidden")
                logger.error("Please check your API credentials")
                return False
            else:
                logger.warning(f"Authentication verification returned unexpected status: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"Authentication verification failed with exception: {e}")
            return False

    def _load_dimension_mapping(self) -> Dict[str, UUID]:
        """
        Load dimension mapping from API dynamically

        Returns:
            Dictionary mapping dimension names to UUIDs
        """
        mapping = {}

        # Skip if authentication is disabled
        if not self.use_auth:
            logger.info("Authentication disabled, skipping dimension loading")
            return mapping

        try:
            # Fetch dimensions from API
            response = self.session.get(f"{self.api_base_url}/api/v1/dimensions/")
            if response.status_code == 200:
                dimensions = response.json()
                mapping = {dim['name']: UUID(dim['id']) for dim in dimensions}
                logger.info(f"Loaded {len(mapping)} dimensions from API")
            elif response.status_code == 403:
                logger.error(f"Authentication failed when loading dimensions: {response.text}")
                logger.error("Please check your API credentials in .env file")
                raise RuntimeError("Authentication failed when loading dimensions")
            else:
                logger.warning(f"Failed to fetch dimensions from API: {response.status_code}")
        except Exception as e:
            logger.error(f"Could not fetch dimensions from API: {e}")
            if self.use_auth:
                raise RuntimeError(f"Failed to load dimensions: {e}")

        return mapping

    def _get_or_create_dimension(self, dimension_name: str) -> UUID:
        """
        Get dimension ID by name, create if not exists

        Args:
            dimension_name: Name of the dimension

        Returns:
            Dimension UUID
        """
        # Skip if authentication is disabled
        if not self.use_auth:
            logger.warning(f"Authentication disabled, cannot create dimension: {dimension_name}")
            return None

        # Check if dimension exists in cache
        if dimension_name in self.dimension_mapping:
            return self.dimension_mapping[dimension_name]

        # Try to fetch from API again (in case it was created by another process)
        try:
            response = self.session.get(f"{self.api_base_url}/api/v1/dimensions/")
            if response.status_code == 200:
                dimensions = response.json()
                for dim in dimensions:
                    if dim['name'] == dimension_name:
                        dimension_uuid = UUID(dim['id'])
                        self.dimension_mapping[dimension_name] = dimension_uuid
                        logger.info(f"Found existing dimension: {dimension_name} (ID: {dimension_uuid})")
                        return dimension_uuid
            elif response.status_code == 403:
                logger.error(f"Authentication failed when fetching dimensions: {response.text}")
                logger.error("Please check your API credentials in .env file")
                return None
        except Exception as e:
            logger.warning(f"Could not fetch dimensions from API: {e}")

        # Create new dimension
        try:
            # Generate a color based on dimension name
            import hashlib
            color_hash = hashlib.md5(dimension_name.encode()).hexdigest()[:6]
            color = f"#{color_hash}"

            dimension_data = {
                "name": dimension_name,
                "description": f"自动创建的维度: {dimension_name}",
                "color": color,
                "icon": "custom",
                "display_order": len(self.dimension_mapping) + 1
            }

            # Ensure we have proper headers including authentication
            headers = {"Content-Type": "application/json"}
            if self.access_token:
                headers["Authorization"] = f"Bearer {self.access_token}"

            response = self.session.post(
                f"{self.api_base_url}/api/v1/dimensions/",
                json=dimension_data,
                headers=headers
            )

            if response.status_code == 201:
                created_dimension = response.json()
                dimension_uuid = UUID(created_dimension['id'])
                self.dimension_mapping[dimension_name] = dimension_uuid
                logger.info(f"Created new dimension: {dimension_name} (ID: {dimension_uuid})")
                return dimension_uuid
            elif response.status_code == 400 and "already exists" in response.text:
                # Dimension already exists, try to get it again
                logger.info(f"Dimension {dimension_name} already exists, fetching ID...")
                response = self.session.get(f"{self.api_base_url}/api/v1/dimensions/")
                if response.status_code == 200:
                    dimensions = response.json()
                    for dim in dimensions:
                        if dim['name'] == dimension_name:
                            dimension_uuid = UUID(dim['id'])
                            self.dimension_mapping[dimension_name] = dimension_uuid
                            logger.info(f"Retrieved existing dimension: {dimension_name} (ID: {dimension_uuid})")
                            return dimension_uuid
                # If still not found, return None (will be handled as optional)
                logger.warning(f"Could not find dimension {dimension_name}, will be set to None")
                return None
            elif response.status_code == 403:
                logger.error(f"Authentication failed when creating dimension {dimension_name}: {response.text}")
                logger.error("Please check your API credentials in .env file")
                # Try to re-authenticate once
                try:
                    logger.info("Attempting to re-authenticate...")
                    self.session, self.api_base_url, self.access_token = login_with_env()
                    logger.info("Re-authentication successful, retrying dimension creation...")
                    # Retry the request with new authentication
                    headers = {"Content-Type": "application/json"}
                    if self.access_token:
                        headers["Authorization"] = f"Bearer {self.access_token}"

                    response = self.session.post(
                        f"{self.api_base_url}/api/v1/dimensions/",
                        json=dimension_data,
                        headers=headers
                    )

                    if response.status_code == 201:
                        created_dimension = response.json()
                        dimension_uuid = UUID(created_dimension['id'])
                        self.dimension_mapping[dimension_name] = dimension_uuid
                        logger.info(f"Created new dimension after re-auth: {dimension_name} (ID: {dimension_uuid})")
                        return dimension_uuid
                    else:
                        logger.error(f"Still failed after re-authentication: {response.status_code} - {response.text}")
                        return None
                except Exception as auth_error:
                    logger.error(f"Re-authentication failed: {auth_error}")
                    return None
            else:
                logger.error(f"Failed to create dimension {dimension_name}: {response.status_code} - {response.text}")
                # Return None if creation fails
                return None

        except Exception as e:
            logger.error(f"Error creating dimension {dimension_name}: {e}")
            # Return None if creation fails
            return None

    def parse_txt_file(self, file_path: str) -> List[TimeEntry]:
        """
        Parse the input .txt file and return list of time entries

        Args:
            file_path: Path to the input .txt file

        Returns:
            List of TimeEntry objects

        Raises:
            FileNotFoundError: If the file doesn't exist
            ValueError: If the file format is invalid
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Input file not found: {file_path}")

        entries = []
        line_number = 0

        with open(file_path, 'r', encoding='utf-8') as file:
            for line in file:
                line_number += 1
                line = line.strip()

                if not line or line.startswith('#'):
                    continue

                try:
                    # Split by tab character
                    parts = line.split('\t')
                    if len(parts) < 6:
                        raise ValueError(f"Expected at least 6 columns, got {len(parts)}")

                    # Extract the first 5 columns
                    date = parts[0]
                    start_time = parts[1]
                    end_time = parts[2]
                    duration = parts[3]
                    dimension = parts[4]

                    # Merge remaining columns into description with comma separation
                    # Filter out empty strings from the remaining parts
                    remaining_parts = [part.strip() for part in parts[5:] if part.strip()]
                    description = ','.join(remaining_parts) if remaining_parts else parts[5]

                    # Create TimeEntry object
                    entry = TimeEntry(
                        date=date.strip(),
                        start_time=start_time.strip(),
                        end_time=end_time.strip(),
                        duration_minutes=int(duration.strip()),
                        dimension=dimension.strip(),
                        description=description.strip()
                    )
                    entries.append(entry)

                except (ValueError, ValidationError) as e:
                    logger.error(f"Error parsing line {line_number}: {line}")
                    logger.error(f"Error details: {e}")
                    continue

        logger.info(f"Successfully parsed {len(entries)} entries from {file_path}")
        return entries

    def process_time_entries(self, entries: List[TimeEntry]) -> List[ProcessedTimeEntry]:
        """
        Process time entries and convert them to API-ready format

        Args:
            entries: List of TimeEntry objects from the input file

        Returns:
            List of ProcessedTimeEntry objects ready for API submission
        """
        processed_entries = []

        for entry in entries:
            try:
                # Parse date and times
                date_obj = datetime.strptime(entry.date, '%Y-%m-%d')
                start_time_obj = datetime.strptime(entry.start_time, '%H:%M').time()
                end_time_obj = datetime.strptime(entry.end_time, '%H:%M').time()

                # Combine date and times
                start_datetime = datetime.combine(date_obj.date(), start_time_obj)
                end_datetime = datetime.combine(date_obj.date(), end_time_obj)

                # Handle end time on next day if needed
                # Check if end time is earlier than start time (crossing midnight)
                if end_time_obj < start_time_obj:
                    end_datetime = datetime.combine(date_obj.date() + timedelta(days=1), end_time_obj)

                # Get or create dimension ID
                dimension_id = self._get_or_create_dimension(entry.dimension)

                # Create processed entry
                processed_entry = ProcessedTimeEntry(
                    title=entry.description,
                    start_time=start_datetime,
                    end_time=end_datetime,
                    dimension_id=dimension_id,
                    tracking_method="batch_import",
                    location=None,
                    energy_level=None,
                    notes=None,
                    tags=None,
                    extra_data=None,
                    task_id=None,
                    person_ids=None
                )

                processed_entries.append(processed_entry)

            except Exception as e:
                logger.error(f"Error processing entry {entry}: {e}")
                continue

        logger.info(f"Successfully processed {len(processed_entries)} entries")
        return processed_entries

    def save_json_data(self, processed_entries: List[ProcessedTimeEntry], output_file: str) -> None:
        """
        Save processed data to JSON file for review

        Args:
            processed_entries: List of processed time entries
            output_file: Path to output JSON file
        """
        # Convert to dict format for JSON serialization
        json_data = []
        for entry in processed_entries:
            entry_dict = entry.model_dump()
            # Convert datetime objects to ISO format strings with timezone
            entry_dict['start_time'] = entry_dict['start_time'].isoformat()
            entry_dict['end_time'] = entry_dict['end_time'].isoformat()

            # Ensure timezone info is included (add +08:00 if not present)
            if '+' not in entry_dict['start_time'] and 'Z' not in entry_dict['start_time']:
                entry_dict['start_time'] += '+08:00'
            if '+' not in entry_dict['end_time'] and 'Z' not in entry_dict['end_time']:
                entry_dict['end_time'] += '+08:00'
            # Convert UUID objects to strings for JSON serialization
            if entry_dict.get('dimension_id'):
                entry_dict['dimension_id'] = str(entry_dict['dimension_id'])
            if entry_dict.get('task_id'):
                entry_dict['task_id'] = str(entry_dict['task_id'])
            # Remove None values to clean up the JSON
            entry_dict = {k: v for k, v in entry_dict.items() if v is not None}
            json_data.append(entry_dict)

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)

        logger.info(f"Processed data saved to {output_file}")

    def submit_to_api(self, processed_entries: List[ProcessedTimeEntry],
                     dry_run: bool = True, batch_size: int = 50) -> Tuple[int, int]:
        """
        Submit processed entries to the API in batches

        Args:
            processed_entries: List of processed time entries
            dry_run: If True, only validate without submitting
            batch_size: Number of entries to submit in each batch

        Returns:
            Tuple of (success_count, failure_count)
        """
        # Check authentication if not in dry run mode
        if not dry_run and self.use_auth and not self.is_authenticated():
            logger.error("Cannot submit to API: Authentication required but not authenticated")
            raise RuntimeError("Authentication required for API submission")

        success_count = 0
        failure_count = 0
        total_entries = len(processed_entries)

        # Process entries in batches
        for batch_start in range(0, total_entries, batch_size):
            batch_end = min(batch_start + batch_size, total_entries)
            batch = processed_entries[batch_start:batch_end]
            batch_num = (batch_start // batch_size) + 1
            total_batches = (total_entries + batch_size - 1) // batch_size

            logger.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} entries)")

            if dry_run:
                logger.info(f"[DRY RUN] Would submit batch {batch_num} with {len(batch)} entries")
                success_count += len(batch)
                continue

            # Submit batch to API
            batch_success, batch_failure = self._submit_batch(batch, batch_start + 1)
            success_count += batch_success
            failure_count += batch_failure

            logger.info(f"Batch {batch_num} completed: {batch_success} success, {batch_failure} failed")

        return success_count, failure_count

    def _submit_batch(self, batch: List[ProcessedTimeEntry], start_index: int) -> Tuple[int, int]:
        """
        Submit a single batch of entries to the API using batch create endpoint

        Args:
            batch: List of entries to submit
            start_index: Starting index for logging purposes

        Returns:
            Tuple of (success_count, failure_count)
        """
        try:
            # Convert all entries to API format
            events_data = []
            for entry in batch:
                api_data = entry.model_dump()
                # Convert datetime objects to ISO format strings with timezone
                api_data['start_time'] = api_data['start_time'].isoformat()
                api_data['end_time'] = api_data['end_time'].isoformat()

                # Ensure timezone info is included (add +08:00 if not present)
                if '+' not in api_data['start_time'] and 'Z' not in api_data['start_time']:
                    api_data['start_time'] += '+08:00'
                if '+' not in api_data['end_time'] and 'Z' not in api_data['end_time']:
                    api_data['end_time'] += '+08:00'
                # Convert UUID objects to strings for JSON serialization
                if api_data.get('dimension_id'):
                    api_data['dimension_id'] = str(api_data['dimension_id'])
                if api_data.get('task_id'):
                    api_data['task_id'] = str(api_data['task_id'])
                # Remove None values to clean up the payload
                api_data = {k: v for k, v in api_data.items() if v is not None}
                events_data.append(api_data)

            # Submit each event individually (fallback if batch-create fails)
            success_count = 0
            failure_count = 0

            headers = {"Content-Type": "application/json"}
            if self.access_token:
                headers["Authorization"] = f"Bearer {self.access_token}"

            for i, event_data in enumerate(events_data):
                try:
                    response = self.session.post(
                        f"{self.api_base_url}/api/v1/actual-events/",
                        json=event_data,
                        headers=headers
                    )

                    if response.status_code == 201:
                        success_count += 1
                    else:
                        logger.error(f"Failed to create event {i+1}: {response.status_code} - {response.text}")
                        failure_count += 1

                except Exception as e:
                    logger.error(f"Error creating event {i+1}: {e}")
                    failure_count += 1

            return success_count, failure_count

        except Exception as e:
            logger.error(f"Error submitting batch: {e}")
            return 0, len(batch)

    def run_import(self, input_file: str, output_file: Optional[str] = None,
                  dry_run: bool = True) -> None:
        """
        Run the complete import process

        Args:
            input_file: Path to input .txt file
            output_file: Path to output JSON file (optional)
            dry_run: If True, only validate without submitting to API
        """
        logger.info(f"Starting batch import process...")
        logger.info(f"Input file: {input_file}")
        logger.info(f"Dry run: {dry_run}")

        # Check authentication status
        if self.use_auth:
            if self.is_authenticated():
                logger.info("✅ Authentication verified - proceeding with import")
            else:
                logger.error("❌ Authentication failed - cannot proceed with import")
                raise RuntimeError("Authentication failed - cannot proceed with import")
        else:
            logger.info("ℹ️ Authentication disabled - proceeding with import")

        try:
            # Step 1: Parse input file
            logger.info("Step 1: Parsing input file...")
            entries = self.parse_txt_file(input_file)
            logger.info(f"✅ Parsed {len(entries)} entries from input file")

            # Step 2: Process entries
            logger.info("Step 2: Processing entries...")
            processed_entries = self.process_time_entries(entries)
            logger.info(f"✅ Processed {len(processed_entries)} entries")

            # Step 3: Save to JSON if output file specified
            if output_file:
                logger.info("Step 3: Saving to JSON file...")
                self.save_json_data(processed_entries, output_file)
                logger.info(f"✅ Data saved to {output_file}")

            # Step 4: Submit to API
            logger.info("Step 4: Submitting to API...")
            success_count, failure_count = self.submit_to_api(processed_entries, dry_run)

            # Summary
            logger.info(f"🎉 Import completed!")
            logger.info(f"Total entries processed: {len(processed_entries)}")
            logger.info(f"Successful submissions: {success_count}")
            logger.info(f"Failed submissions: {failure_count}")

            if failure_count > 0:
                logger.warning(f"⚠️ {failure_count} submissions failed - check logs for details")

        except Exception as e:
            logger.error(f"❌ Import process failed: {e}")
            logger.error("Please check your configuration and try again")
            raise


def create_reusable_api_client(api_base_url: str = "http://localhost:8000", use_auth: bool = True):
    """
    Create a reusable API client for time entry submission

    Args:
        api_base_url: Base URL for the Common Compass API
        use_auth: Whether to use authentication (default: True)

    Returns:
        Function that can be used to submit time entries
    """
    # Initialize session with authentication
    session = None
    if use_auth:
        try:
            load_env_from_root()
            session, api_base_url, access_token = login_with_env()
            logger.info(f"API client authenticated with {api_base_url}")
        except Exception as e:
            logger.warning(f"API client authentication failed: {e}")
            session = requests.Session()
    else:
        session = requests.Session()

    def submit_time_entry(entry_data: Dict) -> Tuple[bool, str]:
        """
        Submit a single time entry to the API

        Args:
            entry_data: Dictionary containing time entry data

        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            # Ensure proper formatting for single entry submission
            formatted_data = entry_data.copy()
            if 'start_time' in formatted_data and isinstance(formatted_data['start_time'], datetime):
                formatted_data['start_time'] = formatted_data['start_time'].isoformat()
            if 'end_time' in formatted_data and isinstance(formatted_data['end_time'], datetime):
                formatted_data['end_time'] = formatted_data['end_time'].isoformat()
            if 'dimension_id' in formatted_data and formatted_data['dimension_id']:
                formatted_data['dimension_id'] = str(formatted_data['dimension_id'])
            if 'task_id' in formatted_data and formatted_data['task_id']:
                formatted_data['task_id'] = str(formatted_data['task_id'])

            headers = {"Content-Type": "application/json"}
            # Note: The session should already have Authorization header set from login_with_env
            # But we can also explicitly set it if we have the token
            if 'access_token' in locals() and access_token:
                headers["Authorization"] = f"Bearer {access_token}"

            response = session.post(
                f"{api_base_url}/api/v1/actual-events/",
                json=formatted_data,
                headers=headers
            )

            if response.status_code == 201:
                return True, "Successfully submitted"
            else:
                return False, f"API error: {response.status_code} - {response.text}"

        except Exception as e:
            return False, f"Request error: {str(e)}"

    return submit_time_entry


def main():
    """Main function for command line usage"""
    import argparse

    parser = argparse.ArgumentParser(description="Batch import time tracking data")
    parser.add_argument("input_file", help="Path to input .txt file")
    parser.add_argument("--output", "-o", help="Path to output JSON file")
    parser.add_argument("--api-url", default="http://localhost:8000",
                       help="API base URL (default: http://localhost:8000)")
    parser.add_argument("--submit", action="store_true",
                       help="Actually submit to API (default is dry run)")
    parser.add_argument("--no-auth", action="store_true",
                       help="Disable authentication (use for testing or if API doesn't require auth)")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Enable verbose logging")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Create importer and run
    use_auth = not args.no_auth
    importer = BatchTimeImporter(args.api_url, use_auth=use_auth)
    importer.run_import(
        input_file=args.input_file,
        output_file=args.output,
        dry_run=not args.submit
    )


if __name__ == "__main__":
    main()
