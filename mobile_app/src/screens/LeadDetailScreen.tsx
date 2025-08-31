import React, { useState, useEffect } from 'react';
import {
  View,
  ScrollView,
  Alert,
  StyleSheet,
  Linking,
} from 'react-native';
import {
  Card,
  Title,
  Paragraph,
  Button,
  Chip,
  FAB,
  ActivityIndicator,
  Divider,
  List,
} from 'react-native-paper';
import { StackNavigationProp } from '@react-navigation/stack';
import { RouteProp } from '@react-navigation/native';
import { RootStackParamList } from '../../App';
import { LeadWithActivities, LEAD_STATUSES } from '../types/Lead';
import LeadsService from '../services/LeadsService';

type LeadDetailScreenNavigationProp = StackNavigationProp<RootStackParamList, 'LeadDetail'>;
type LeadDetailScreenRouteProp = RouteProp<RootStackParamList, 'LeadDetail'>;

interface Props {
  navigation: LeadDetailScreenNavigationProp;
  route: LeadDetailScreenRouteProp;
}

const LeadDetailScreen: React.FC<Props> = ({ navigation, route }) => {
  const { leadId } = route.params;
  const [leadData, setLeadData] = useState<LeadWithActivities | null>(null);
  const [loading, setLoading] = useState(true);

  const loadLeadData = async () => {
    try {
      const data = await LeadsService.getLead(leadId);
      setLeadData(data);
    } catch (error) {
      Alert.alert('Error', 'Failed to load lead details');
      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadLeadData();
  }, [leadId]);

  const handleCall = () => {
    if (leadData?.lead.phone) {
      const phoneUrl = `tel:${leadData.lead.phone}`;
      Linking.canOpenURL(phoneUrl).then((supported) => {
        if (supported) {
          Linking.openURL(phoneUrl);
          // Add call activity
          LeadsService.addActivity(leadId, {
            user_name: 'current_user', // TODO: Get from user context
            activity_type: 'call_outbound',
            description: `Called ${leadData.lead.phone}`,
          }).then(() => {
            loadLeadData(); // Refresh data
          });
        } else {
          Alert.alert('Error', 'Phone calls not supported on this device');
        }
      });
    }
  };

  const handleEmail = () => {
    if (leadData?.lead.email) {
      const emailUrl = `mailto:${leadData.lead.email}`;
      Linking.openURL(emailUrl);
    }
  };

  const handleStatusChange = (newStatus: string) => {
    Alert.alert(
      'Change Status',
      `Change lead status to ${newStatus}?`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Confirm',
          onPress: async () => {
            try {
              await LeadsService.updateLeadStatus(leadId, newStatus, 'current_user');
              loadLeadData(); // Refresh data
            } catch (error) {
              Alert.alert('Error', 'Failed to update status');
            }
          },
        },
      ]
    );
  };

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'new': return '#2196F3';
      case 'contacted': return '#FF9800';
      case 'qualified': return '#4CAF50';
      case 'interested': return '#8BC34A';
      case 'not_interested': return '#F44336';
      case 'callback': return '#9C27B0';
      case 'converted': return '#00C853';
      case 'closed': return '#757575';
      default: return '#757575';
    }
  };

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString('he-IL', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit'
    });
  };

  const getActivityIcon = (activityType: string) => {
    switch (activityType) {
      case 'call_outbound': return '📞';
      case 'call_inbound': return '📲';
      case 'email_sent': return '📧';
      case 'note_added': return '📝';
      case 'status_changed': return '🔄';
      default: return '📋';
    }
  };

  if (loading) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  if (!leadData) {
    return (
      <View style={styles.centered}>
        <Paragraph>Lead not found</Paragraph>
      </View>
    );
  }

  const { lead, activities } = leadData;

  return (
    <View style={styles.container}>
      <ScrollView style={styles.scrollView}>
        {/* Lead Info Card */}
        <Card style={styles.card}>
          <Card.Content>
            <View style={styles.header}>
              <Title style={styles.leadName}>{lead.name || 'No Name'}</Title>
              <Chip 
                style={[styles.statusChip, { backgroundColor: getStatusColor(lead.status) }]}
                textStyle={styles.statusText}
              >
                {lead.status.toUpperCase()}
              </Chip>
            </View>

            <Paragraph style={styles.email}>✉️ {lead.email}</Paragraph>
            {lead.phone && <Paragraph style={styles.phone}>📞 {lead.phone}</Paragraph>}
            
            <Divider style={styles.divider} />
            
            <Paragraph>📱 Platform: {lead.platform}</Paragraph>
            <Paragraph>📅 Received: {formatDate(lead.received_at)}</Paragraph>
            {lead.campaign_name && <Paragraph>🎯 Campaign: {lead.campaign_name}</Paragraph>}
            {lead.form_name && <Paragraph>📋 Form: {lead.form_name}</Paragraph>}
          </Card.Content>
        </Card>

        {/* Action Buttons */}
        <Card style={styles.card}>
          <Card.Content>
            <Title>Actions</Title>
            <View style={styles.actionButtons}>
              <Button 
                mode="contained" 
                onPress={handleCall}
                disabled={!lead.phone}
                style={styles.actionButton}
                icon="phone"
              >
                Call
              </Button>
              <Button 
                mode="contained" 
                onPress={handleEmail}
                disabled={!lead.email}
                style={styles.actionButton}
                icon="email"
              >
                Email
              </Button>
            </View>
          </Card.Content>
        </Card>

        {/* Status Change */}
        <Card style={styles.card}>
          <Card.Content>
            <Title>Change Status</Title>
            <View style={styles.statusButtons}>
              {LEAD_STATUSES.filter(status => status !== lead.status).map((status) => (
                <Button
                  key={status}
                  mode="outlined"
                  onPress={() => handleStatusChange(status)}
                  style={styles.statusButton}
                  compact
                >
                  {status}
                </Button>
              ))}
            </View>
          </Card.Content>
        </Card>

        {/* Activities */}
        <Card style={styles.card}>
          <Card.Content>
            <Title>Activity History</Title>
            {activities.length === 0 ? (
              <Paragraph>No activities yet</Paragraph>
            ) : (
              activities.map((activity) => (
                <List.Item
                  key={activity.id}
                  title={`${getActivityIcon(activity.activity_type)} ${activity.activity_type.replace('_', ' ')}`}
                  description={`${activity.description} - by ${activity.user_name}`}
                  right={() => (
                    <Paragraph style={styles.activityTime}>
                      {formatDate(activity.created_at)}
                    </Paragraph>
                  )}
                />
              ))
            )}
          </Card.Content>
        </Card>

        {/* Raw Data (for debugging) */}
        {lead.raw_data && (
          <Card style={styles.card}>
            <Card.Content>
              <Title>Raw Data</Title>
              <Paragraph style={styles.rawData}>
                {JSON.stringify(lead.raw_data, null, 2)}
              </Paragraph>
            </Card.Content>
          </Card>
        )}
      </ScrollView>

      {/* Floating Action Button */}
      <FAB
        icon="plus"
        style={styles.fab}
        onPress={() => navigation.navigate('AddActivity', { leadId })}
      />
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f5f5f5',
  },
  centered: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  scrollView: {
    flex: 1,
  },
  card: {
    margin: 16,
    marginBottom: 8,
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16,
  },
  leadName: {
    fontSize: 24,
    fontWeight: 'bold',
    flex: 1,
  },
  statusChip: {
    marginLeft: 8,
  },
  statusText: {
    color: 'white',
    fontSize: 12,
    fontWeight: 'bold',
  },
  email: {
    fontSize: 16,
    marginBottom: 8,
  },
  phone: {
    fontSize: 16,
    marginBottom: 8,
  },
  divider: {
    marginVertical: 16,
  },
  actionButtons: {
    flexDirection: 'row',
    justifyContent: 'space-around',
    marginTop: 16,
  },
  actionButton: {
    flex: 1,
    marginHorizontal: 8,
  },
  statusButtons: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    marginTop: 8,
  },
  statusButton: {
    margin: 4,
  },
  activityTime: {
    fontSize: 12,
    color: '#666',
  },
  rawData: {
    fontFamily: 'monospace',
    fontSize: 10,
    backgroundColor: '#f0f0f0',
    padding: 8,
  },
  fab: {
    position: 'absolute',
    margin: 16,
    right: 0,
    bottom: 0,
  },
});

export default LeadDetailScreen;