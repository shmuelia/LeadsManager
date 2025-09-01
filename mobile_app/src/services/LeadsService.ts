import { Lead, LeadActivity, LeadWithActivities } from '../types/Lead';

const API_BASE_URL = 'https://eadmanager-fresh-2024-dev-f83e51d73e01.herokuapp.com';

class LeadsService {
  async getLeads(): Promise<{ total_leads: number; leads: Lead[] }> {
    const response = await fetch(`${API_BASE_URL}/leads`);
    if (!response.ok) {
      throw new Error('Failed to fetch leads');
    }
    return response.json();
  }

  async getLead(leadId: number): Promise<LeadWithActivities> {
    const response = await fetch(`${API_BASE_URL}/leads/${leadId}`);
    if (!response.ok) {
      throw new Error('Failed to fetch lead details');
    }
    return response.json();
  }

  async addActivity(leadId: number, activity: {
    user_name: string;
    activity_type: string;
    description?: string;
    call_duration?: number;
    call_outcome?: string;
    new_status?: string;
    metadata?: any;
  }): Promise<{ status: string; activity_id: number }> {
    const response = await fetch(`${API_BASE_URL}/leads/${leadId}/activity`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(activity),
    });
    
    if (!response.ok) {
      throw new Error('Failed to add activity');
    }
    return response.json();
  }

  async updateLeadStatus(leadId: number, status: string, userName: string): Promise<{ status: string }> {
    const response = await fetch(`${API_BASE_URL}/leads/${leadId}/status`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        status,
        user_name: userName,
      }),
    });
    
    if (!response.ok) {
      throw new Error('Failed to update lead status');
    }
    return response.json();
  }
}

export default new LeadsService();