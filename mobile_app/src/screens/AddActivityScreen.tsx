import React, { useState } from 'react';
import {
  View,
  ScrollView,
  Alert,
  StyleSheet,
} from 'react-native';
import {
  TextInput,
  Button,
  Title,
  RadioButton,
  Card,
  Paragraph,
  Chip,
} from 'react-native-paper';
import { StackNavigationProp } from '@react-navigation/stack';
import { RouteProp } from '@react-navigation/native';
import { RootStackParamList } from '../../App';
import { ACTIVITY_TYPES, CALL_OUTCOMES, LEAD_STATUSES } from '../types/Lead';
import LeadsService from '../services/LeadsService';

type AddActivityScreenNavigationProp = StackNavigationProp<RootStackParamList, 'AddActivity'>;
type AddActivityScreenRouteProp = RouteProp<RootStackParamList, 'AddActivity'>;

interface Props {
  navigation: AddActivityScreenNavigationProp;
  route: AddActivityScreenRouteProp;
}

const AddActivityScreen: React.FC<Props> = ({ navigation, route }) => {
  const { leadId } = route.params;
  const [activityType, setActivityType] = useState('note_added');
  const [description, setDescription] = useState('');
  const [callDuration, setCallDuration] = useState('');
  const [callOutcome, setCallOutcome] = useState('');
  const [newStatus, setNewStatus] = useState('');
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    if (!description.trim()) {
      Alert.alert('Error', 'Please enter a description');
      return;
    }

    setSaving(true);
    try {
      const activity = {
        user_name: 'current_user', // TODO: Get from user context
        activity_type: activityType,
        description: description.trim(),
        call_duration: callDuration ? parseInt(callDuration) * 60 : undefined, // convert minutes to seconds
        call_outcome: callOutcome || undefined,
        new_status: newStatus || undefined,
      };

      await LeadsService.addActivity(leadId, activity);
      Alert.alert('Success', 'Activity added successfully', [
        { text: 'OK', onPress: () => navigation.goBack() }
      ]);
    } catch (error) {
      Alert.alert('Error', 'Failed to add activity');
      console.error(error);
    } finally {
      setSaving(false);
    }
  };

  const isCallActivity = activityType.includes('call');

  return (
    <ScrollView style={styles.container}>
      <Card style={styles.card}>
        <Card.Content>
          <Title>Add New Activity</Title>
          
          {/* Activity Type */}
          <Paragraph style={styles.sectionTitle}>Activity Type</Paragraph>
          <View style={styles.chipContainer}>
            {ACTIVITY_TYPES.map((type) => (
              <Chip
                key={type}
                selected={activityType === type}
                onPress={() => setActivityType(type)}
                style={styles.chip}
              >
                {type.replace('_', ' ')}
              </Chip>
            ))}
          </View>

          {/* Description */}
          <TextInput
            label="Description"
            value={description}
            onChangeText={setDescription}
            multiline
            numberOfLines={4}
            style={styles.input}
            placeholder="Enter activity description..."
          />

          {/* Call-specific fields */}
          {isCallActivity && (
            <>
              <TextInput
                label="Call Duration (minutes)"
                value={callDuration}
                onChangeText={setCallDuration}
                keyboardType="numeric"
                style={styles.input}
                placeholder="e.g. 5"
              />

              <Paragraph style={styles.sectionTitle}>Call Outcome</Paragraph>
              <RadioButton.Group onValueChange={setCallOutcome} value={callOutcome}>
                {CALL_OUTCOMES.map((outcome) => (
                  <RadioButton.Item
                    key={outcome}
                    label={outcome.replace('_', ' ')}
                    value={outcome}
                  />
                ))}
              </RadioButton.Group>
            </>
          )}

          {/* Status Change */}
          <Paragraph style={styles.sectionTitle}>Change Lead Status (Optional)</Paragraph>
          <View style={styles.chipContainer}>
            <Chip
              selected={newStatus === ''}
              onPress={() => setNewStatus('')}
              style={styles.chip}
            >
              No Change
            </Chip>
            {LEAD_STATUSES.map((status) => (
              <Chip
                key={status}
                selected={newStatus === status}
                onPress={() => setNewStatus(status)}
                style={styles.chip}
              >
                {status}
              </Chip>
            ))}
          </View>

          {/* Save Button */}
          <Button
            mode="contained"
            onPress={handleSave}
            loading={saving}
            disabled={saving}
            style={styles.saveButton}
          >
            Save Activity
          </Button>
        </Card.Content>
      </Card>
    </ScrollView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f5f5f5',
  },
  card: {
    margin: 16,
  },
  sectionTitle: {
    fontSize: 16,
    fontWeight: 'bold',
    marginTop: 16,
    marginBottom: 8,
  },
  chipContainer: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    marginBottom: 16,
  },
  chip: {
    margin: 4,
  },
  input: {
    marginBottom: 16,
  },
  saveButton: {
    marginTop: 24,
  },
});

export default AddActivityScreen;