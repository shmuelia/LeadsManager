export interface Lead {
  id: number;
  external_lead_id?: string;
  name?: string;
  email?: string;
  phone?: string;
  platform: string;
  campaign_name?: string;
  form_name?: string;
  lead_source?: string;
  created_time?: string;
  received_at: string;
  status: string;
  assigned_to?: string;
  priority: number;
  raw_data: any;
  notes?: string;
  updated_at: string;
}

export interface LeadActivity {
  id: number;
  lead_id: number;
  user_name: string;
  activity_type: string;
  description?: string;
  call_duration?: number;
  call_outcome?: string;
  created_at: string;
  metadata?: any;
}

export interface LeadWithActivities {
  lead: Lead;
  activities: LeadActivity[];
}

export const LEAD_STATUSES = [
  'new',
  'contacted', 
  'qualified',
  'interested',
  'not_interested',
  'callback',
  'converted',
  'closed'
];

export const ACTIVITY_TYPES = [
  'call_outbound',
  'call_inbound', 
  'email_sent',
  'email_received',
  'sms_sent',
  'sms_received',
  'note_added',
  'status_changed',
  'assigned',
  'callback_scheduled',
  'meeting_scheduled'
];

export const CALL_OUTCOMES = [
  'answered',
  'voicemail', 
  'no_answer',
  'busy',
  'invalid_number'
];