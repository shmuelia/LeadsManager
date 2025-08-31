import React from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { createStackNavigator } from '@react-navigation/stack';
import { Provider as PaperProvider } from 'react-native-paper';
import { StatusBar } from 'expo-status-bar';

import LeadsListScreen from './src/screens/LeadsListScreen';
import LeadDetailScreen from './src/screens/LeadDetailScreen';
import AddActivityScreen from './src/screens/AddActivityScreen';

export type RootStackParamList = {
  LeadsList: undefined;
  LeadDetail: { leadId: number };
  AddActivity: { leadId: number };
};

const Stack = createStackNavigator<RootStackParamList>();

export default function App() {
  return (
    <PaperProvider>
      <NavigationContainer>
        <Stack.Navigator initialRouteName="LeadsList">
          <Stack.Screen 
            name="LeadsList" 
            component={LeadsListScreen}
            options={{ title: 'Leads Manager' }}
          />
          <Stack.Screen 
            name="LeadDetail" 
            component={LeadDetailScreen}
            options={{ title: 'Lead Details' }}
          />
          <Stack.Screen 
            name="AddActivity" 
            component={AddActivityScreen}
            options={{ title: 'Add Activity' }}
          />
        </Stack.Navigator>
        <StatusBar style="auto" />
      </NavigationContainer>
    </PaperProvider>
  );
}