import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  FlatList,
  RefreshControl,
  Alert,
  StyleSheet,
  Linking,
  I18nManager,
} from 'react-native';
import {
  Card,
  Title,
  Paragraph,
  Chip,
  FAB,
  Searchbar,
  ActivityIndicator,
  Button,
  IconButton,
} from 'react-native-paper';

// Enable RTL for Hebrew
I18nManager.forceRTL(true);
import { useFocusEffect } from '@react-navigation/native';
import { StackNavigationProp } from '@react-navigation/stack';
import { RootStackParamList } from '../../App';
import { Lead } from '../types/Lead';
import LeadsService from '../services/LeadsService';

type LeadsListScreenNavigationProp = StackNavigationProp<RootStackParamList, 'LeadsList'>;

interface Props {
  navigation: LeadsListScreenNavigationProp;
}

const LeadsListScreen: React.FC<Props> = ({ navigation }) => {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');

  const loadLeads = async () => {
    try {
      const data = await LeadsService.getLeads();
      setLeads(data.leads);
    } catch (error) {
      Alert.alert('Error', 'Failed to load leads');
      console.error(error);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useFocusEffect(
    useCallback(() => {
      loadLeads();
    }, [])
  );

  const onRefresh = () => {
    setRefreshing(true);
    loadLeads();
  };

  const filteredLeads = leads.filter(lead =>
    (lead.name?.toLowerCase().includes(searchQuery.toLowerCase()) || '') ||
    (lead.email?.toLowerCase().includes(searchQuery.toLowerCase()) || '') ||
    (lead.phone?.includes(searchQuery) || '')
  );

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

  const handleCall = (phone: string, leadName: string) => {
    const phoneUrl = `tel:${phone}`;
    Linking.canOpenURL(phoneUrl).then((supported) => {
      if (supported) {
        Linking.openURL(phoneUrl);
      } else {
        Alert.alert('שגיאה', 'לא ניתן לבצע שיחה במכשיר זה');
      }
    });
  };

  const handleWhatsApp = (phone: string) => {
    const whatsappUrl = `whatsapp://send?phone=${phone}&text=שלום, התקבל פנייתך למשרה באלחנן מאפיית לחם`;
    Linking.canOpenURL(whatsappUrl).then((supported) => {
      if (supported) {
        Linking.openURL(whatsappUrl);
      } else {
        Alert.alert('שגיאה', 'WhatsApp לא מותקן במכשיר');
      }
    });
  };

  const renderLeadItem = ({ item }: { item: Lead }) => (
    <Card style={styles.card} elevation={2}>
      <Card.Content>
        {/* Header with name and status */}
        <View style={styles.cardHeader}>
          <Title style={styles.leadName}>{item.name || 'אין שם'}</Title>
          <Chip 
            style={[styles.statusChip, { backgroundColor: getStatusColor(item.status) }]}
            textStyle={styles.statusText}
          >
            {item.status === 'new' ? 'חדש' : item.status}
          </Chip>
        </View>
        
        {/* Contact info */}
        <View style={styles.contactInfo}>
          <Paragraph style={styles.email}>✉️ {item.email}</Paragraph>
          {item.phone && (
            <Paragraph style={styles.phone}>📱 {item.phone}</Paragraph>
          )}
        </View>
        
        {/* Quick actions */}
        {item.phone && (
          <View style={styles.actionButtons}>
            <Button 
              mode="contained" 
              icon="phone"
              onPress={() => handleCall(item.phone!, item.name || 'ליד')}
              style={styles.callButton}
              buttonColor="#4CAF50"
            >
              התקשר
            </Button>
            <Button 
              mode="outlined" 
              icon="whatsapp"
              onPress={() => handleWhatsApp(item.phone!)}
              style={styles.whatsappButton}
              textColor="#25D366"
            >
              WhatsApp
            </Button>
          </View>
        )}
        
        {/* Meta info */}
        <View style={styles.metaInfo}>
          <Paragraph style={styles.platform}>
            📱 {item.platform === 'ig' ? 'אינסטגרם' : item.platform} • 📅 {formatDate(item.received_at)}
          </Paragraph>
        </View>
        
        {/* Campaign info */}
        {item.campaign_name && (
          <Paragraph style={styles.campaign} numberOfLines={1}>
            🎯 {item.campaign_name}
          </Paragraph>
        )}
        
        {/* View details button */}
        <Button 
          mode="text" 
          onPress={() => navigation.navigate('LeadDetail', { leadId: item.id })}
          style={styles.detailsButton}
        >
          פרטים מלאים ←
        </Button>
      </Card.Content>
    </Card>
  );

  if (loading) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator size="large" />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <Searchbar
        placeholder="חפש לידים..."
        onChangeText={setSearchQuery}
        value={searchQuery}
        style={styles.searchbar}
        right={() => <IconButton icon="magnify" />}
      />
      
      <FlatList
        data={filteredLeads}
        renderItem={renderLeadItem}
        keyExtractor={(item) => item.id.toString()}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
        }
        contentContainerStyle={styles.listContent}
      />
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f8f9fa',
  },
  centered: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  searchbar: {
    margin: 16,
    marginBottom: 8,
    elevation: 2,
  },
  listContent: {
    padding: 8,
  },
  card: {
    margin: 12,
    borderRadius: 12,
    backgroundColor: 'white',
  },
  cardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  leadName: {
    fontSize: 20,
    fontWeight: 'bold',
    flex: 1,
    color: '#1a1a1a',
    textAlign: 'right',
  },
  statusChip: {
    marginLeft: 8,
  },
  statusText: {
    color: 'white',
    fontSize: 11,
    fontWeight: 'bold',
  },
  contactInfo: {
    marginBottom: 12,
  },
  email: {
    fontSize: 16,
    color: '#333',
    marginBottom: 4,
    textAlign: 'right',
  },
  phone: {
    fontSize: 16,
    color: '#333',
    marginBottom: 4,
    textAlign: 'right',
  },
  actionButtons: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 12,
  },
  callButton: {
    flex: 1,
    marginRight: 8,
  },
  whatsappButton: {
    flex: 1,
    marginLeft: 8,
  },
  metaInfo: {
    marginBottom: 8,
  },
  platform: {
    fontSize: 13,
    color: '#666',
    textAlign: 'right',
  },
  campaign: {
    fontSize: 12,
    color: '#888',
    fontStyle: 'italic',
    marginBottom: 8,
    textAlign: 'right',
  },
  detailsButton: {
    alignSelf: 'flex-end',
  },
});

export default LeadsListScreen;