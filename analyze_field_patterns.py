"""
Analyze field name patterns across all leads to identify variations
This will help determine if we need a configuration page for field mapping
"""
import os
import psycopg2
import psycopg2.extras
import json
from urllib.parse import urlparse
from collections import defaultdict

DATABASE_URL = os.environ.get('DATABASE_URL')

def analyze_field_patterns():
    """Analyze all leads to find field name patterns"""
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL not set")
        return

    parsed_url = urlparse(DATABASE_URL)
    conn = psycopg2.connect(
        database=parsed_url.path[1:],
        user=parsed_url.username,
        password=parsed_url.password,
        host=parsed_url.hostname,
        port=parsed_url.port
    )

    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Get all leads with raw_data
    cur.execute("""
        SELECT id, name, email, phone, raw_data, campaign_name, created_time
        FROM leads
        WHERE raw_data IS NOT NULL
        ORDER BY id DESC
    """)

    leads = cur.fetchall()

    # Track field patterns
    field_patterns = defaultdict(set)  # field_type -> set of field names found
    campaign_patterns = defaultdict(lambda: defaultdict(set))  # campaign -> field_type -> field names

    # Categorize field names
    phone_keywords = ['phone', 'טלפון', 'mobile', 'cell']
    email_keywords = ['email', 'mail', 'דואר', 'דוא"ל']
    name_keywords = ['name', 'שם', 'full']

    for lead in leads:
        raw_data = lead['raw_data']
        if isinstance(raw_data, str):
            try:
                raw_data = json.loads(raw_data)
            except:
                continue

        if not raw_data or not isinstance(raw_data, dict):
            continue

        campaign = lead.get('campaign_name', 'Unknown')

        for field_name in raw_data.keys():
            field_lower = field_name.lower()

            # Categorize the field
            if any(keyword in field_lower for keyword in phone_keywords):
                field_patterns['phone'].add(field_name)
                campaign_patterns[campaign]['phone'].add(field_name)
            elif any(keyword in field_lower for keyword in email_keywords):
                field_patterns['email'].add(field_name)
                campaign_patterns[campaign]['email'].add(field_name)
            elif any(keyword in field_lower for keyword in name_keywords):
                field_patterns['name'].add(field_name)
                campaign_patterns[campaign]['name'].add(field_name)

    # Print analysis
    print("\n=== FIELD NAME VARIATIONS FOUND ===\n")

    print("PHONE FIELDS:")
    for field in sorted(field_patterns['phone']):
        print(f"  - {field}")

    print("\nEMAIL FIELDS:")
    for field in sorted(field_patterns['email']):
        print(f"  - {field}")

    print("\nNAME FIELDS:")
    for field in sorted(field_patterns['name']):
        print(f"  - {field}")

    print("\n=== VARIATIONS BY CAMPAIGN ===\n")

    for campaign in sorted(campaign_patterns.keys()):
        if campaign and campaign != 'None':
            print(f"\nCampaign: {campaign}")
            if campaign_patterns[campaign]['phone']:
                print(f"  Phone: {', '.join(sorted(campaign_patterns[campaign]['phone']))}")
            if campaign_patterns[campaign]['email']:
                print(f"  Email: {', '.join(sorted(campaign_patterns[campaign]['email']))}")
            if campaign_patterns[campaign]['name']:
                print(f"  Name: {', '.join(sorted(campaign_patterns[campaign]['name']))}")

    # Check for consistency issues
    print("\n=== CONSISTENCY ANALYSIS ===\n")

    if len(field_patterns['phone']) > 3:
        print("⚠️  HIGH VARIATION: Found {} different phone field names".format(len(field_patterns['phone'])))
        print("   Recommendation: Consider adding field mapping configuration")

    if len(field_patterns['email']) > 3:
        print("⚠️  HIGH VARIATION: Found {} different email field names".format(len(field_patterns['email'])))

    if len(field_patterns['name']) > 3:
        print("⚠️  HIGH VARIATION: Found {} different name field names".format(len(field_patterns['name'])))

    # Check if any campaigns have unique patterns
    unique_patterns = []
    for campaign, patterns in campaign_patterns.items():
        for field_type, field_names in patterns.items():
            for field_name in field_names:
                # Check if this field name is unique to this campaign
                other_campaigns_with_field = sum(1 for c, p in campaign_patterns.items()
                                                if c != campaign and field_name in p.get(field_type, set()))
                if other_campaigns_with_field == 0 and campaign != 'Unknown':
                    unique_patterns.append((campaign, field_type, field_name))

    if unique_patterns:
        print("\n⚠️  CAMPAIGN-SPECIFIC FIELDS FOUND:")
        for campaign, field_type, field_name in unique_patterns:
            print(f"   Campaign '{campaign}' has unique {field_type} field: '{field_name}'")

    cur.close()
    conn.close()

if __name__ == "__main__":
    analyze_field_patterns()