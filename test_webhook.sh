#!/bin/bash

# Test webhook with sample data including custom fields
# This simulates what Zapier should be sending

echo "Testing webhook with form data..."

curl -X POST https://eadmanager-fresh-2024-dev-f83e51d73e01.herokuapp.com/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "name": "TEST User Form Data",
    "email": "testform@example.com",
    "phone": "+972501234567",
    "platform": "facebook",
    "campaign_name": "Test Campaign",
    "form_name": "טופס בדיקה עם שאלות",
    "created_time": "2025-01-02T10:00:00Z",
    "custom_question_0": "מה התאריך הרצוי לקיום האירוע?",
    "custom_answer_0": "15 בינואר 2025",
    "custom_question_1": "כמות האנשים שצפויה להגיע?",
    "custom_answer_1": "50-75 אנשים",
    "custom_question_2": "סוג האירוע?",
    "custom_answer_2": "יום הולדת",
    "custom_question_3": "תקציב משוער?",
    "custom_answer_3": "5000-7000 שקל",
    "שם": "TEST User Form Data",
    "דוא\"ל": "testform@example.com",
    "טלפון": "+972501234567",
    "טופס": "טופס בדיקה עם שאלות",
    "מקור": "בתשלום",
    "ערוץ": "Facebook",
    "שלב": "קליטה",
    "בעלים": "Unassigned"
  }'

echo ""
echo "Test sent! Check the lead at:"
echo "https://eadmanager-fresh-2024-dev-f83e51d73e01.herokuapp.com/campaign-manager"
echo ""
echo "Or check debug info at:"
echo "https://eadmanager-fresh-2024-dev-f83e51d73e01.herokuapp.com/debug/search/TEST"