import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  FlatList,
  RefreshControl,
  Alert,
  StyleSheet,
} from 'react-native';
import {
  Card,
  Title,
  Paragraph,
  Chip,
  FAB,
  Searchbar,
  ActivityIndicator,
} from 'react-native-paper';
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

  const renderLeadItem = ({ item }: { item: Lead }) => (
    <Card
      style={styles.card}
      onPress={() => navigation.navigate('LeadDetail', { leadId: item.id })}
    >
      <Card.Content>
        <View style={styles.cardHeader}>
          <Title style={styles.leadName}>{item.name || 'No Name'}</Title>
          <Chip 
            style={[styles.statusChip, { backgroundColor: getStatusColor(item.status) }]}
            textStyle={styles.statusText}
          >
            {item.status.toUpperCase()}
          </Chip>
        </View>
        
        <Paragraph style={styles.email}>{item.email}</Paragraph>
        {item.phone && <Paragraph style={styles.phone}>📞 {item.phone}</Paragraph>}
        
        <View style={styles.metaInfo}>
          <Paragraph style={styles.platform}>
            📱 {item.platform} | 📅 {formatDate(item.received_at)}
          </Paragraph>
        </View>
        
        {item.campaign_name && (
          <Paragraph style={styles.campaign} numberOfLines={1}>
            🎯 {item.campaign_name}
          </Paragraph>
        )}
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
        placeholder="Search leads..."
        onChangeText={setSearchQuery}
        value={searchQuery}
        style={styles.searchbar}
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
    backgroundColor: '#f5f5f5',
  },
  centered: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  searchbar: {
    margin: 16,
    marginBottom: 8,
  },
  listContent: {
    padding: 8,
  },
  card: {
    margin: 8,
    elevation: 2,
  },
  cardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  leadName: {
    fontSize: 18,
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
    color: '#666',
    marginBottom: 4,
  },
  phone: {
    color: '#666',
    marginBottom: 8,
  },
  metaInfo: {
    marginBottom: 4,
  },
  platform: {
    fontSize: 12,
    color: '#888',
  },
  campaign: {
    fontSize: 12,
    color: '#888',
    fontStyle: 'italic',
  },
});

export default LeadsListScreen;