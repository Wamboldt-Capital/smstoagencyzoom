#!/usr/bin/env python3
"""Helper script to find Todoist section IDs."""

import os
import sys
import requests

def main():
    token = os.getenv("TODOIST_API_TOKEN")
    project_id = sys.argv[1] if len(sys.argv) > 1 else None

    if not token:
        print("ERROR: Set TODOIST_API_TOKEN environment variable")
        sys.exit(1)

    if not project_id:
        print("ERROR: Provide project ID as argument")
        print("Usage: python get_todoist_section_id.py <project_id>")
        print("Example: python get_todoist_section_id.py inbound-messages-6f7xhQPJr6vFXFhc")
        sys.exit(1)

    # Get sections for the project
    url = f"https://api.todoist.com/rest/v2/sections?project_id={project_id}"
    headers = {"Authorization": f"Bearer {token}"}

    print(f"Fetching sections for project: {project_id}\n")

    try:
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        sections = response.json()

        if not sections:
            print("No sections found in this project.")
            print("Create a section in Todoist first, then run this script again.")
            sys.exit(0)

        print("Available sections:")
        print("-" * 60)
        for section in sections:
            print(f"Name: {section['name']}")
            print(f"ID:   {section['id']}")
            print("-" * 60)

        print("\nTo use a section, set this in your GitHub Secrets:")
        print("TODOIST_SECTION_ID = <section_id>")

    except requests.exceptions.RequestException as e:
        print(f"ERROR: Failed to fetch sections: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
