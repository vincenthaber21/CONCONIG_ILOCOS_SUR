import React, { useState, useEffect, useRef } from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { StatusBar } from 'expo-status-bar';
import { AppState, View, Text, Image, ActivityIndicator, StyleSheet } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { authService, accountService, setLogoutCallback, getInMemorySession } from './services/api';
import { fetchStoreBrandAssets } from './utils/storeBrand';

import LoginScreen from './screens/LoginScreen';
import HomeScreen from './screens/HomeScreen';
import TransactionsScreen from './screens/TransactionsScreen';
import FundTransferScreen from './screens/FundTransferScreen';
import ProductsScreen from './screens/ProductsScreen';
import SettingsScreen from './screens/SettingsScreen';
import AdminOverviewScreen from './screens/AdminOverviewScreen';

const Stack = createNativeStackNavigator();
const Tab = createBottomTabNavigator();

function MainTabs() {
  const [isAdmin, setIsAdmin] = useState(false);

  useEffect(() => {
    let mounted = true;

    const loadRole = async () => {
      const member = await authService.getStoredMember();
      const memberType = (member?.member_type || member?.member_type_name || '').toString().toLowerCase();
      if (mounted) {
        setIsAdmin(memberType.includes('admin'));
      }
    };

    loadRole();
    return () => {
      mounted = false;
    };
  }, []);

  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        tabBarIcon: ({ focused, color, size }) => {
          let iconName;

          if (route.name === 'Home') {
            iconName = focused ? 'home' : 'home-outline';
          } else if (route.name === 'FundTransfer') {
            iconName = focused ? 'swap-horizontal' : 'swap-horizontal-outline';
          } else if (route.name === 'Transactions') {
            iconName = focused ? 'receipt' : 'receipt-outline';
          } else if (route.name === 'Products') {
            iconName = focused ? 'pricetag' : 'pricetag-outline';
          } else if (route.name === 'Admin') {
            iconName = focused ? 'shield-checkmark' : 'shield-checkmark-outline';
          } else if (route.name === 'Settings') {
            iconName = focused ? 'settings' : 'settings-outline';
          }

          return <Ionicons name={iconName} size={size} color={color} />;
        },
        tabBarActiveTintColor: '#ED1C24',
        tabBarInactiveTintColor: '#94a3b8',
        headerShown: false,
      })}
    >
      <Tab.Screen
        name="Home"
        component={HomeScreen}
        options={{
          tabBarLabel: 'Home',
        }}
      />
      <Tab.Screen
        name="FundTransfer"
        component={FundTransferScreen}
        options={{
          tabBarLabel: 'Fund Transfer',
        }}
      />
      <Tab.Screen
        name="Transactions"
        component={TransactionsScreen}
        options={{
          tabBarLabel: 'Transactions',
        }}
      />
      <Tab.Screen
        name="Products"
        component={ProductsScreen}
        options={{
          tabBarLabel: 'Products',
        }}
      />
      {isAdmin ? (
        <Tab.Screen
          name="Admin"
          component={AdminOverviewScreen}
          options={{
            tabBarLabel: 'Admin',
          }}
        />
      ) : null}
      <Tab.Screen
        name="Settings"
        component={SettingsScreen}
        options={{
          tabBarLabel: 'Settings',
        }}
      />
    </Tab.Navigator>
  );
}

export default function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [bootBrand, setBootBrand] = useState({ logoUrl: '', systemName: '' });
  const navigationRef = useRef(null);
  const appState = useRef(AppState.currentState);

  useEffect(() => {
    checkAuth();

    // Register auto-logout callback: called by the 401 interceptor or
    // triggerAutoLogout() whenever the session becomes invalid.
    setLogoutCallback(() => {
      setIsAuthenticated(false);
    });

    // Re-validate session whenever the app returns to the foreground.
    // This catches the case where the user cleared app data via system settings
    // while the app was backgrounded.
    const subscription = AppState.addEventListener('change', async (nextState) => {
      if (appState.current.match(/inactive|background/) && nextState === 'active') {
        // App resumed — check if storage was externally cleared (e.g. Settings → Clear Data)
        const member = await AsyncStorage.getItem('memberData');
        if (!member) {
          setIsAuthenticated(false);
        }
      }
      appState.current = nextState;
    });

    return () => {
      setLogoutCallback(null);
      subscription.remove();
    };
  }, []);

  const checkAuth = async () => {
    const brandPromise = fetchStoreBrandAssets().catch(() => ({
      logoUrl: '',
      systemName: '',
    }));

    try {
      const memberData = await AsyncStorage.getItem('memberData');
      const inMemorySession = getInMemorySession();

      // ── Cold-start detection ──────────────────────────────────────────────
      // _inMemorySession is a module-level variable that lives only in the JS
      // heap. It is set after every successful login and is automatically null
      // when the process starts fresh (i.e. after the user swipes the app away
      // from the recent-apps screen or the OS kills the process).
      // If AsyncStorage still holds member data but the memory marker is gone,
      // the process was restarted — treat it as a logout so the user must
      // authenticate again.
      if (memberData && !inMemorySession) {
        await authService.clearSession();
        setIsAuthenticated(false);
        return;
      }

      const member = memberData ? JSON.parse(memberData) : null;
      if (member) {
        // Validate the existing server session (app was resuming, not restarted)
        try {
          const accountResponse = await accountService.getAccountInfo();
          if (accountResponse && accountResponse.success) {
            setIsAuthenticated(true);
            return;
          }
        } catch (error) {
          // Session invalid — fall through to show Login screen
        }
      }

      // No valid session — always show Login screen.
      // Never auto-login; the user must enter their PIN or use biometrics.
      await authService.clearSession();
      setIsAuthenticated(false);
    } catch (error) {
      // Clear session only to preserve fingerprint credentials
      await authService.clearSession();
      setIsAuthenticated(false);
    } finally {
      const brand = await brandPromise;
      setBootBrand(brand);
      setIsLoading(false);
    }
  };

  if (isLoading) {
    return (
      <View style={bootStyles.wrap}>
        <StatusBar style="dark" />
        {bootBrand.logoUrl ? (
          <Image
            source={{ uri: bootBrand.logoUrl }}
            style={bootStyles.logo}
            resizeMode="contain"
            accessibilityRole="image"
            accessibilityLabel="Store logo"
          />
        ) : null}
        {bootBrand.systemName ? (
          <View style={bootStyles.titleWrap}>
            <Text style={bootStyles.title} numberOfLines={4}>
              {bootBrand.systemName}
            </Text>
          </View>
        ) : null}
        <ActivityIndicator style={bootStyles.spinner} color="#ED1C24" />
      </View>
    );
  }

  return (
    <NavigationContainer ref={navigationRef}>
      <StatusBar style="auto" />
      <Stack.Navigator 
        screenOptions={{ headerShown: false }}
        initialRouteName={isAuthenticated ? "Main" : "Login"}
      >
        <Stack.Screen name="Login" component={LoginScreen} />
        <Stack.Screen name="Main" component={MainTabs} />
      </Stack.Navigator>
    </NavigationContainer>
  );
}

const bootStyles = StyleSheet.create({
  wrap: {
    flex: 1,
    backgroundColor: '#ffffff',
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 32,
  },
  logo: {
    width: 160,
    height: 160,
    marginBottom: 16,
  },
  titleWrap: {
    alignSelf: 'stretch',
    marginBottom: 8,
  },
  title: {
    fontSize: 18,
    fontWeight: '700',
    color: '#111827',
    textAlign: 'center',
    lineHeight: 24,
    letterSpacing: 0.2,
  },
  spinner: {
    marginTop: 20,
  },
});
