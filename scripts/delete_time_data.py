#!/usr/bin/env python3
"""
Delete Time Data Script

This script deletes actual events within a specified time range.
Use this script to clean up erroneous data imported with bugs.
"""

import logging
import sys
from datetime import datetime, timedelta
from typing import List, Optional

import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class TimeDataDeleter:
    """Class for deleting time tracking data within a specified range"""

    def __init__(self, api_base_url: str = "http://localhost:8000"):
        """
        Initialize the time data deleter

        Args:
            api_base_url: Base URL for the Common Compass API
        """
        self.api_base_url = api_base_url.rstrip('/')

    def get_events_in_range(self, start_date: datetime, end_date: datetime,
                           tracking_method: Optional[str] = None) -> List[dict]:
        """
        Get all events within the specified time range

        Args:
            start_date: Start of time range
            end_date: End of time range
            tracking_method: Optional filter by tracking method

        Returns:
            List of event data
        """
        try:
            # Build query parameters
            params = {
                'start': start_date.isoformat(),
                'end': end_date.isoformat(),
            }

            if tracking_method:
                params['tracking_method'] = tracking_method

            response = requests.get(
                f"{self.api_base_url}/api/v1/actual-events/",
                params=params
            )

            if response.status_code == 200:
                events = response.json()
                logger.info(f"Found {len(events)} events in time range")
                return events
            else:
                logger.error(f"Failed to fetch events: {response.status_code} - {response.text}")
                return []

        except Exception as e:
            logger.error(f"Error fetching events: {e}")
            return []

    def delete_events(self, event_ids: List[str], hard_delete: bool = False) -> dict:
        """
        Delete multiple events by their IDs

        Args:
            event_ids: List of event IDs to delete
            hard_delete: Whether to permanently delete (default: soft delete)

        Returns:
            Dictionary with deletion results
        """
        if not event_ids:
            return {"deleted_count": 0, "failed_count": 0, "errors": []}

        try:
            # Use batch delete endpoint
            data = {"event_ids": event_ids}
            params = {"hard_delete": str(hard_delete).lower()}

            response = requests.post(
                f"{self.api_base_url}/api/v1/actual-events/batch-delete",
                json=data,
                params=params
            )

            if response.status_code == 200:
                result = response.json()
                logger.info(f"Batch delete completed: {result.get('deleted_count', 0)} deleted, {len(result.get('failed_ids', []))} failed")
                return result
            else:
                logger.error(f"Failed to delete events: {response.status_code} - {response.text}")
                return {"deleted_count": 0, "failed_count": len(event_ids), "errors": [f"API error: {response.status_code}"]}

        except Exception as e:
            logger.error(f"Error deleting events: {e}")
            return {"deleted_count": 0, "failed_count": len(event_ids), "errors": [str(e)]}

    def delete_events_in_range(self, start_date: datetime, end_date: datetime,
                              tracking_method: Optional[str] = None,
                              hard_delete: bool = False,
                              dry_run: bool = True) -> dict:
        """
        Delete all events within the specified time range (day by day)

        Args:
            start_date: Start of time range
            end_date: End of time range
            tracking_method: Optional filter by tracking method
            hard_delete: Whether to permanently delete (default: soft delete)
            dry_run: If True, only show what would be deleted

        Returns:
            Dictionary with deletion results
        """
        logger.info(f"Searching for events from {start_date} to {end_date}")
        if tracking_method:
            logger.info(f"Filtering by tracking method: {tracking_method}")

        total_deleted = 0
        total_failed = 0
        all_errors = []

        # Process day by day to avoid API limits
        current_date = start_date.date()
        end_date_only = end_date.date()

        while current_date <= end_date_only:
            day_start = datetime.combine(current_date, datetime.min.time())
            day_end = datetime.combine(current_date, datetime.max.time().replace(microsecond=999999))

            logger.info(f"Processing date: {current_date}")

            # Get events for this day
            events = self.get_events_in_range(day_start, day_end, tracking_method)

            if not events:
                logger.info(f"No events found for {current_date}")
                current_date += timedelta(days=1)
                continue

            # Extract event IDs
            event_ids = [event['id'] for event in events]

            if dry_run:
                logger.info(f"[DRY RUN] Would delete {len(event_ids)} events for {current_date}:")
                for event in events[:3]:  # Show first 3 events
                    logger.info(f"  - ID {event['id']}: {event['title']} ({event['start_time']} - {event['end_time']})")
                if len(events) > 3:
                    logger.info(f"  ... and {len(events) - 3} more events")
                total_deleted += len(event_ids)
            else:
                # Actually delete events for this day
                logger.info(f"Deleting {len(event_ids)} events for {current_date}...")
                result = self.delete_events(event_ids, hard_delete)
                total_deleted += result.get('deleted_count', 0)
                total_failed += result.get('failed_count', 0)
                all_errors.extend(result.get('errors', []))

            current_date += timedelta(days=1)

        return {
            "deleted_count": total_deleted,
            "failed_count": total_failed,
            "errors": all_errors
        }


def main():
    """Main function for command line usage"""
    import argparse

    parser = argparse.ArgumentParser(description="Delete time tracking data within a specified range")
    parser.add_argument("--start-date", required=True,
                       help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", required=True,
                       help="End date (YYYY-MM-DD)")
    parser.add_argument("--api-url", default="http://localhost:8000",
                       help="API base URL (default: http://localhost:8000)")
    parser.add_argument("--tracking-method",
                       help="Only delete events with specific tracking method (e.g., 'batch_import')")
    parser.add_argument("--hard-delete", action="store_true",
                       help="Permanently delete events (default is soft delete)")
    parser.add_argument("--submit", action="store_true",
                       help="Actually delete events (default is dry run)")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Enable verbose logging")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Parse dates
    try:
        start_date = datetime.strptime(args.start_date, '%Y-%m-%d')
        end_date = datetime.strptime(args.end_date, '%Y-%m-%d')
        # Set time to cover full days
        start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)
        end_date = end_date.replace(hour=23, minute=59, second=59, microsecond=999999)
    except ValueError as e:
        logger.error(f"Invalid date format: {e}")
        sys.exit(1)

    # Create deleter
    deleter = TimeDataDeleter(args.api_url)

    # Delete events
    result = deleter.delete_events_in_range(
        start_date=start_date,
        end_date=end_date,
        tracking_method=args.tracking_method,
        hard_delete=args.hard_delete,
        dry_run=not args.submit
    )

    # Print results
    print(f"\nDeletion Results:")
    print(f"  Deleted: {result.get('deleted_count', 0)}")
    print(f"  Failed: {result.get('failed_count', 0)}")

    if result.get('errors'):
        print(f"  Errors:")
        for error in result['errors']:
            print(f"    - {error}")

    if not args.submit:
        print(f"\nThis was a dry run. Use --submit to actually delete the events.")


if __name__ == "__main__":
    main()
