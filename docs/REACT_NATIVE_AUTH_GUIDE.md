# React Native Authentication Guide

## Overview

This guide explains how to implement authentication and session persistence in your React Native app with the Markt API backend. The backend uses Flask-Login for session management, which means authentication is handled through HTTP cookies rather than JWT tokens.

## Key Concepts

### Flask-Login vs JWT Authentication

Unlike JWT-based authentication where you receive a token and send it in headers, Flask-Login uses:
- **Session cookies**: Authentication state is stored in HTTP cookies
- **Server-side sessions**: Session data is stored on the server (Redis in our case)
- **Automatic cookie handling**: The browser/HTTP client automatically sends cookies with requests

### Session Persistence

The backend automatically handles session persistence through:
- **Session cookies**: Named `markt_session` (configurable)
- **Redis storage**: Session data stored server-side with expiration
- **CORS support**: Configured to allow credentials from your app

## Implementation Guide

### 1. HTTP Client Setup

You need to configure your HTTP client to handle cookies properly. Here are examples for different HTTP libraries:

#### Using Axios

```javascript
import axios from 'axios';
import AsyncStorage from '@react-native-async-storage/async-storage';

// Create axios instance
const apiClient = axios.create({
  baseURL: 'https://your-api-domain.com/api/v1',
  timeout: 10000,
  withCredentials: true, // This is crucial for cookie handling
});

// Request interceptor to add common headers
apiClient.interceptors.request.use(
  async (config) => {
    // Add any common headers here
    config.headers['Content-Type'] = 'application/json';
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Response interceptor to handle authentication errors
apiClient.interceptors.response.use(
  (response) => {
    return response;
  },
  async (error) => {
    if (error.response?.status === 401) {
      // Handle unauthorized - redirect to login
      await AsyncStorage.removeItem('user_session');
      // Navigate to login screen
      // navigation.navigate('Login');
    }
    return Promise.reject(error);
  }
);

export default apiClient;
```

#### Using Fetch API

```javascript
const API_BASE_URL = 'https://your-api-domain.com/api/v1';

class ApiService {
  static async request(endpoint, options = {}) {
    const url = `${API_BASE_URL}${endpoint}`;
    
    const defaultOptions = {
      credentials: 'include', // This is crucial for cookie handling
      headers: {
        'Content-Type': 'application/json',
      },
    };

    const config = {
      ...defaultOptions,
      ...options,
      headers: {
        ...defaultOptions.headers,
        ...options.headers,
      },
    };

    try {
      const response = await fetch(url, config);
      
      if (response.status === 401) {
        // Handle unauthorized
        await AsyncStorage.removeItem('user_session');
        throw new Error('Unauthorized');
      }
      
      return response;
    } catch (error) {
      throw error;
    }
  }
}
```

### 2. Authentication Service

Create a service to handle authentication operations:

```javascript
import apiClient from './apiClient';
import AsyncStorage from '@react-native-async-storage/async-storage';

class AuthService {
  // Register a new user
  static async register(userData) {
    try {
      const response = await apiClient.post('/users/register', userData);
      
      // Store user data locally for quick access
      await AsyncStorage.setItem('user_session', JSON.stringify({
        user: response.data,
        timestamp: Date.now(),
      }));
      
      return response.data;
    } catch (error) {
      throw this.handleError(error);
    }
  }

  // Login user
  static async login(email, password, accountType = null) {
    try {
      const response = await apiClient.post('/users/login', {
        email,
        password,
        account_type: accountType,
      });
      
      // Store user data locally
      await AsyncStorage.setItem('user_session', JSON.stringify({
        user: response.data,
        timestamp: Date.now(),
      }));
      
      return response.data;
    } catch (error) {
      throw this.handleError(error);
    }
  }

  // Logout user
  static async logout() {
    try {
      await apiClient.post('/users/logout');
      await AsyncStorage.removeItem('user_session');
    } catch (error) {
      // Even if logout fails on server, clear local storage
      await AsyncStorage.removeItem('user_session');
      throw this.handleError(error);
    }
  }

  // Get current user profile
  static async getCurrentUser() {
    try {
      const response = await apiClient.get('/users/profile');
      return response.data;
    } catch (error) {
      throw this.handleError(error);
    }
  }

  // Send email verification
  static async sendEmailVerification(email) {
    try {
      const response = await apiClient.post('/users/email-verification/send', {
        email,
      });
      return response.data;
    } catch (error) {
      throw this.handleError(error);
    }
  }

  // Verify email with code
  static async verifyEmail(email, verificationCode) {
    try {
      const response = await apiClient.post('/users/email-verification/verify', {
        email,
        verification_code: verificationCode,
      });
      return response.data;
    } catch (error) {
      throw this.handleError(error);
    }
  }

  // Check if user is logged in locally
  static async isLoggedIn() {
    try {
      const sessionData = await AsyncStorage.getItem('user_session');
      if (!sessionData) return false;
      
      const { timestamp } = JSON.parse(sessionData);
      const now = Date.now();
      const sessionAge = now - timestamp;
      
      // Consider session expired after 7 days of inactivity
      if (sessionAge > 7 * 24 * 60 * 60 * 1000) {
        await AsyncStorage.removeItem('user_session');
        return false;
      }
      
      return true;
    } catch (error) {
      return false;
    }
  }

  // Get stored user data
  static async getStoredUser() {
    try {
      const sessionData = await AsyncStorage.getItem('user_session');
      if (!sessionData) return null;
      
      const { user, timestamp } = JSON.parse(sessionData);
      const now = Date.now();
      const sessionAge = now - timestamp;
      
      // Return user data if session is not too old
      if (sessionAge < 7 * 24 * 60 * 60 * 1000) {
        return user;
      }
      
      return null;
    } catch (error) {
      return null;
    }
  }

  // Refresh user data from server
  static async refreshUserData() {
    try {
      const userData = await this.getCurrentUser();
      await AsyncStorage.setItem('user_session', JSON.stringify({
        user: userData,
        timestamp: Date.now(),
      }));
      return userData;
    } catch (error) {
      // If refresh fails, user might be logged out
      await AsyncStorage.removeItem('user_session');
      throw this.handleError(error);
    }
  }

  // Handle API errors
  static handleError(error) {
    if (error.response) {
      // Server responded with error status
      const { status, data } = error.response;
      
      switch (status) {
        case 400:
          return new Error(data.message || 'Bad request');
        case 401:
          return new Error('Unauthorized - please login again');
        case 403:
          return new Error('Forbidden - insufficient permissions');
        case 404:
          return new Error('Resource not found');
        case 409:
          return new Error(data.message || 'Conflict - resource already exists');
        case 422:
          return new Error(data.message || 'Unverified email - please verify your email');
        case 500:
          return new Error('Server error - please try again later');
        default:
          return new Error(data.message || 'An error occurred');
      }
    } else if (error.request) {
      // Network error
      return new Error('Network error - please check your connection');
    } else {
      // Other error
      return new Error(error.message || 'An unexpected error occurred');
    }
  }
}

export default AuthService;
```

### 3. Authentication Context

Create a React Context to manage authentication state:

```javascript
import React, { createContext, useContext, useReducer, useEffect } from 'react';
import AuthService from '../services/AuthService';

const AuthContext = createContext();

const initialState = {
  user: null,
  isAuthenticated: false,
  isLoading: true,
  error: null,
};

function authReducer(state, action) {
  switch (action.type) {
    case 'LOGIN_START':
      return {
        ...state,
        isLoading: true,
        error: null,
      };
    case 'LOGIN_SUCCESS':
      return {
        ...state,
        user: action.payload,
        isAuthenticated: true,
        isLoading: false,
        error: null,
      };
    case 'LOGIN_FAILURE':
      return {
        ...state,
        user: null,
        isAuthenticated: false,
        isLoading: false,
        error: action.payload,
      };
    case 'LOGOUT':
      return {
        ...state,
        user: null,
        isAuthenticated: false,
        isLoading: false,
        error: null,
      };
    case 'SET_LOADING':
      return {
        ...state,
        isLoading: action.payload,
      };
    case 'CLEAR_ERROR':
      return {
        ...state,
        error: null,
      };
    default:
      return state;
  }
}

export function AuthProvider({ children }) {
  const [state, dispatch] = useReducer(authReducer, initialState);

  // Check authentication status on app start
  useEffect(() => {
    checkAuthStatus();
  }, []);

  const checkAuthStatus = async () => {
    try {
      const isLoggedIn = await AuthService.isLoggedIn();
      if (isLoggedIn) {
        const user = await AuthService.getStoredUser();
        if (user) {
          dispatch({ type: 'LOGIN_SUCCESS', payload: user });
        } else {
          // Try to refresh user data from server
          try {
            const freshUser = await AuthService.refreshUserData();
            dispatch({ type: 'LOGIN_SUCCESS', payload: freshUser });
          } catch (error) {
            dispatch({ type: 'LOGOUT' });
          }
        }
      } else {
        dispatch({ type: 'LOGOUT' });
      }
    } catch (error) {
      dispatch({ type: 'LOGOUT' });
    }
  };

  const login = async (email, password, accountType) => {
    dispatch({ type: 'LOGIN_START' });
    try {
      const user = await AuthService.login(email, password, accountType);
      dispatch({ type: 'LOGIN_SUCCESS', payload: user });
      return user;
    } catch (error) {
      dispatch({ type: 'LOGIN_FAILURE', payload: error.message });
      throw error;
    }
  };

  const register = async (userData) => {
    dispatch({ type: 'LOGIN_START' });
    try {
      const user = await AuthService.register(userData);
      dispatch({ type: 'LOGIN_SUCCESS', payload: user });
      return user;
    } catch (error) {
      dispatch({ type: 'LOGIN_FAILURE', payload: error.message });
      throw error;
    }
  };

  const logout = async () => {
    try {
      await AuthService.logout();
    } catch (error) {
      // Ignore logout errors
    } finally {
      dispatch({ type: 'LOGOUT' });
    }
  };

  const sendEmailVerification = async (email) => {
    try {
      return await AuthService.sendEmailVerification(email);
    } catch (error) {
      dispatch({ type: 'LOGIN_FAILURE', payload: error.message });
      throw error;
    }
  };

  const verifyEmail = async (email, verificationCode) => {
    try {
      return await AuthService.verifyEmail(email, verificationCode);
    } catch (error) {
      dispatch({ type: 'LOGIN_FAILURE', payload: error.message });
      throw error;
    }
  };

  const clearError = () => {
    dispatch({ type: 'CLEAR_ERROR' });
  };

  const value = {
    ...state,
    login,
    register,
    logout,
    sendEmailVerification,
    verifyEmail,
    clearError,
    checkAuthStatus,
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
```

### 4. App Setup

Wrap your app with the AuthProvider:

```javascript
import React from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { AuthProvider } from './contexts/AuthContext';
import AppNavigator from './navigation/AppNavigator';

export default function App() {
  return (
    <AuthProvider>
      <NavigationContainer>
        <AppNavigator />
      </NavigationContainer>
    </AuthProvider>
  );
}
```

### 5. Navigation Setup

Create conditional navigation based on authentication status:

```javascript
import React from 'react';
import { createStackNavigator } from '@react-navigation/stack';
import { useAuth } from '../contexts/AuthContext';
import LoginScreen from '../screens/LoginScreen';
import RegisterScreen from '../screens/RegisterScreen';
import HomeScreen from '../screens/HomeScreen';
import LoadingScreen from '../screens/LoadingScreen';

const Stack = createStackNavigator();

export default function AppNavigator() {
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) {
    return <LoadingScreen />;
  }

  return (
    <Stack.Navigator screenOptions={{ headerShown: false }}>
      {isAuthenticated ? (
        // Authenticated screens
        <Stack.Screen name="Home" component={HomeScreen} />
      ) : (
        // Unauthenticated screens
        <>
          <Stack.Screen name="Login" component={LoginScreen} />
          <Stack.Screen name="Register" component={RegisterScreen} />
        </>
      )}
    </Stack.Navigator>
  );
}
```

### 6. Login Screen Example

```javascript
import React, { useState } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  Alert,
  StyleSheet,
} from 'react-native';
import { useAuth } from '../contexts/AuthContext';

export default function LoginScreen({ navigation }) {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [accountType, setAccountType] = useState('buyer');
  const { login, isLoading, error, clearError } = useAuth();

  const handleLogin = async () => {
    if (!email || !password) {
      Alert.alert('Error', 'Please fill in all fields');
      return;
    }

    try {
      clearError();
      await login(email, password, accountType);
      // Navigation will be handled automatically by the navigator
    } catch (error) {
      Alert.alert('Login Failed', error.message);
    }
  };

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Login</Text>
      
      {error && (
        <Text style={styles.errorText}>{error}</Text>
      )}

      <TextInput
        style={styles.input}
        placeholder="Email"
        value={email}
        onChangeText={setEmail}
        keyboardType="email-address"
        autoCapitalize="none"
      />

      <TextInput
        style={styles.input}
        placeholder="Password"
        value={password}
        onChangeText={setPassword}
        secureTextEntry
      />

      <TouchableOpacity
        style={[styles.button, isLoading && styles.buttonDisabled]}
        onPress={handleLogin}
        disabled={isLoading}
      >
        <Text style={styles.buttonText}>
          {isLoading ? 'Logging in...' : 'Login'}
        </Text>
      </TouchableOpacity>

      <TouchableOpacity
        style={styles.linkButton}
        onPress={() => navigation.navigate('Register')}
      >
        <Text style={styles.linkText}>Don't have an account? Register</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    padding: 20,
    justifyContent: 'center',
  },
  title: {
    fontSize: 24,
    fontWeight: 'bold',
    textAlign: 'center',
    marginBottom: 30,
  },
  input: {
    borderWidth: 1,
    borderColor: '#ddd',
    padding: 15,
    marginBottom: 15,
    borderRadius: 8,
  },
  button: {
    backgroundColor: '#007AFF',
    padding: 15,
    borderRadius: 8,
    alignItems: 'center',
    marginBottom: 15,
  },
  buttonDisabled: {
    backgroundColor: '#ccc',
  },
  buttonText: {
    color: 'white',
    fontSize: 16,
    fontWeight: 'bold',
  },
  linkButton: {
    alignItems: 'center',
  },
  linkText: {
    color: '#007AFF',
    fontSize: 14,
  },
  errorText: {
    color: 'red',
    textAlign: 'center',
    marginBottom: 15,
  },
});
```

## Important Notes

### 1. Cookie Handling
- Always set `withCredentials: true` (Axios) or `credentials: 'include'` (Fetch)
- The backend automatically handles session cookies
- Cookies are automatically sent with subsequent requests

### 2. Session Persistence
- Sessions are stored server-side in Redis
- Local storage is used for quick access to user data
- Sessions expire based on server configuration
- Always check server session validity for sensitive operations

### 3. Error Handling
- Handle 401 errors by redirecting to login
- Clear local storage on authentication errors
- Provide user-friendly error messages

### 4. Email Verification
- Email verification is now explicit (not automatic)
- Users must call the verification endpoint manually
- Handle unverified email errors gracefully

### 5. Account Types
- Users can have both buyer and seller accounts
- Specify account type during login
- Use role switching for users with multiple accounts

## Testing

### 1. Test Session Persistence
```javascript
// Test that session persists across app restarts
const testSessionPersistence = async () => {
  // Login
  await AuthService.login('test@example.com', 'password');
  
  // Close and reopen app (simulate)
  // Check if user is still logged in
  const isLoggedIn = await AuthService.isLoggedIn();
  console.log('Session persisted:', isLoggedIn);
};
```

### 2. Test Cookie Handling
```javascript
// Test that cookies are sent with requests
const testCookieHandling = async () => {
  try {
    const response = await apiClient.get('/users/profile');
    console.log('Profile data:', response.data);
  } catch (error) {
    console.log('Cookie test failed:', error.message);
  }
};
```

## Troubleshooting

### Common Issues

1. **Session not persisting**
   - Check if `withCredentials: true` is set
   - Verify CORS configuration allows credentials
   - Check if cookies are being set in response headers

2. **401 errors on protected routes**
   - Session might have expired
   - Check if user is properly logged in
   - Verify cookie is being sent with requests

3. **CORS errors**
   - Ensure backend CORS allows your app's origin
   - Check if credentials are enabled in CORS config

4. **Network errors**
   - Verify API base URL is correct
   - Check network connectivity
   - Ensure backend is running and accessible

### Debug Tips

1. **Check Network Tab**
   - Look for `markt_session` cookie in request headers
   - Verify response includes `Set-Cookie` header

2. **Log Session Data**
   ```javascript
   console.log('Stored session:', await AsyncStorage.getItem('user_session'));
   ```

3. **Test API Endpoints**
   - Use Postman or similar tool to test endpoints
   - Verify authentication works outside the app

## Security Considerations

1. **Local Storage**
   - Don't store sensitive data in AsyncStorage
   - Use it only for user display data
   - Clear data on logout

2. **HTTPS**
   - Always use HTTPS in production
   - Cookies are only secure over HTTPS

3. **Session Management**
   - Implement proper logout functionality
   - Handle session expiration gracefully
   - Don't store passwords locally

This guide provides a complete implementation for React Native authentication with Flask-Login session management. The key difference from JWT-based auth is that you don't need to manually handle tokens - the HTTP client automatically manages session cookies.
