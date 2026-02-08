# Angular Web App Authentication Guide

## Overview

This guide explains how to implement authentication and session persistence in your Angular web application with the Markt API backend. The backend uses Flask-Login for session management, which means authentication is handled through HTTP cookies rather than JWT tokens.

## Key Concepts

### Flask-Login vs JWT Authentication

Unlike JWT-based authentication where you receive a token and send it in headers, Flask-Login uses:
- **Session cookies**: Authentication state is stored in HTTP cookies
- **Server-side sessions**: Session data is stored on the server (Redis in our case)
- **Automatic cookie handling**: The browser automatically sends cookies with requests

### Session Persistence

The backend automatically handles session persistence through:
- **Session cookies**: Named `markt_session` (configurable)
- **Redis storage**: Session data stored server-side with expiration
- **CORS support**: Configured to allow credentials from your app

## Implementation Guide

### 1. HTTP Interceptor Setup

Create an HTTP interceptor to handle authentication and cookies:

```typescript
// src/app/interceptors/auth.interceptor.ts
import { Injectable } from '@angular/core';
import {
  HttpInterceptor,
  HttpRequest,
  HttpHandler,
  HttpEvent,
  HttpErrorResponse,
} from '@angular/common/http';
import { Observable, throwError } from 'rxjs';
import { catchError } from 'rxjs/operators';
import { Router } from '@angular/router';
import { AuthService } from '../services/auth.service';

@Injectable()
export class AuthInterceptor implements HttpInterceptor {
  constructor(
    private authService: AuthService,
    private router: Router
  ) {}

  intercept(
    request: HttpRequest<any>,
    next: HttpHandler
  ): Observable<HttpEvent<any>> {
    // Clone the request to add credentials
    const authRequest = request.clone({
      withCredentials: true, // This is crucial for cookie handling
    });

    return next.handle(authRequest).pipe(
      catchError((error: HttpErrorResponse) => {
        if (error.status === 401) {
          // Handle unauthorized - redirect to login
          this.authService.logout();
          this.router.navigate(['/login']);
        }
        return throwError(error);
      })
    );
  }
}
```

### 2. HTTP Client Configuration

Configure the HTTP client in your app module:

```typescript
// src/app/app.module.ts
import { NgModule } from '@angular/core';
import { BrowserModule } from '@angular/platform-browser';
import { HttpClientModule, HTTP_INTERCEPTORS } from '@angular/common/http';
import { AppRoutingModule } from './app-routing.module';
import { AppComponent } from './app.component';
import { AuthInterceptor } from './interceptors/auth.interceptor';

@NgModule({
  declarations: [
    AppComponent,
    // ... other components
  ],
  imports: [
    BrowserModule,
    AppRoutingModule,
    HttpClientModule,
  ],
  providers: [
    {
      provide: HTTP_INTERCEPTORS,
      useClass: AuthInterceptor,
      multi: true,
    },
  ],
  bootstrap: [AppComponent],
})
export class AppModule {}
```

### 3. Authentication Service

Create a service to handle authentication operations:

```typescript
// src/app/services/auth.service.ts
import { Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { BehaviorSubject, Observable, throwError } from 'rxjs';
import { map, catchError, tap } from 'rxjs/operators';
import { Router } from '@angular/router';

export interface User {
  id: string;
  email: string;
  username: string;
  profile_picture?: string;
  is_buyer: boolean;
  is_seller: boolean;
  email_verified: boolean;
  current_role: string;
  created_at: string;
  updated_at: string;
  last_login_at?: string;
}

export interface LoginRequest {
  email: string;
  password: string;
  account_type?: string;
}

export interface RegisterRequest {
  email: string;
  username: string;
  password: string;
  account_type: 'buyer' | 'seller';
  phone_number?: string;
  buyer_data?: any;
  seller_data?: any;
  address?: any;
}

@Injectable({
  providedIn: 'root',
})
export class AuthService {
  private readonly API_URL = 'https://your-api-domain.com/api/v1';
  private currentUserSubject = new BehaviorSubject<User | null>(null);
  public currentUser$ = this.currentUserSubject.asObservable();

  constructor(
    private http: HttpClient,
    private router: Router
  ) {
    // Check for existing session on service initialization
    this.checkAuthStatus();
  }

  // Check authentication status
  private checkAuthStatus(): void {
    const storedUser = this.getStoredUser();
    if (storedUser) {
      this.currentUserSubject.next(storedUser);
    }
  }

  // Register a new user
  register(userData: RegisterRequest): Observable<User> {
    return this.http.post<User>(`${this.API_URL}/users/register`, userData).pipe(
      tap((user) => {
        this.setStoredUser(user);
        this.currentUserSubject.next(user);
      }),
      catchError(this.handleError)
    );
  }

  // Login user
  login(email: string, password: string, accountType?: string): Observable<User> {
    const loginData: LoginRequest = {
      email,
      password,
      account_type: accountType,
    };

    return this.http.post<User>(`${this.API_URL}/users/login`, loginData).pipe(
      tap((user) => {
        this.setStoredUser(user);
        this.currentUserSubject.next(user);
      }),
      catchError(this.handleError)
    );
  }

  // Logout user
  logout(): Observable<any> {
    return this.http.post(`${this.API_URL}/users/logout`, {}).pipe(
      tap(() => {
        this.clearStoredUser();
        this.currentUserSubject.next(null);
        this.router.navigate(['/login']);
      }),
      catchError((error) => {
        // Even if logout fails on server, clear local storage
        this.clearStoredUser();
        this.currentUserSubject.next(null);
        this.router.navigate(['/login']);
        return throwError(error);
      })
    );
  }

  // Get current user profile
  getCurrentUser(): Observable<User> {
    return this.http.get<User>(`${this.API_URL}/users/profile`).pipe(
      tap((user) => {
        this.setStoredUser(user);
        this.currentUserSubject.next(user);
      }),
      catchError(this.handleError)
    );
  }

  // Send email verification
  sendEmailVerification(email: string): Observable<any> {
    return this.http.post(`${this.API_URL}/users/email-verification/send`, {
      email,
    }).pipe(
      catchError(this.handleError)
    );
  }

  // Verify email with code
  verifyEmail(email: string, verificationCode: string): Observable<any> {
    return this.http.post(`${this.API_URL}/users/email-verification/verify`, {
      email,
      verification_code: verificationCode,
    }).pipe(
      catchError(this.handleError)
    );
  }

  // Check if user is logged in
  isLoggedIn(): boolean {
    const user = this.getStoredUser();
    if (!user) return false;

    const timestamp = user.last_login_at ? new Date(user.last_login_at).getTime() : 0;
    const now = Date.now();
    const sessionAge = now - timestamp;

    // Consider session expired after 7 days of inactivity
    if (sessionAge > 7 * 24 * 60 * 60 * 1000) {
      this.clearStoredUser();
      this.currentUserSubject.next(null);
      return false;
    }

    return true;
  }

  // Get current user from subject
  getCurrentUserValue(): User | null {
    return this.currentUserSubject.value;
  }

  // Refresh user data from server
  refreshUserData(): Observable<User> {
    return this.getCurrentUser().pipe(
      catchError((error) => {
        // If refresh fails, user might be logged out
        this.clearStoredUser();
        this.currentUserSubject.next(null);
        return throwError(error);
      })
    );
  }

  // Store user data in localStorage
  private setStoredUser(user: User): void {
    const sessionData = {
      user,
      timestamp: Date.now(),
    };
    localStorage.setItem('markt_user_session', JSON.stringify(sessionData));
  }

  // Get stored user data
  private getStoredUser(): User | null {
    try {
      const sessionData = localStorage.getItem('markt_user_session');
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

  // Clear stored user data
  private clearStoredUser(): void {
    localStorage.removeItem('markt_user_session');
  }

  // Handle API errors
  private handleError(error: any): Observable<never> {
    let errorMessage = 'An unexpected error occurred';

    if (error.error) {
      const { status, error: errorData } = error.error;
      
      switch (status) {
        case 400:
          errorMessage = errorData.message || 'Bad request';
          break;
        case 401:
          errorMessage = 'Unauthorized - please login again';
          break;
        case 403:
          errorMessage = 'Forbidden - insufficient permissions';
          break;
        case 404:
          errorMessage = 'Resource not found';
          break;
        case 409:
          errorMessage = errorData.message || 'Conflict - resource already exists';
          break;
        case 422:
          errorMessage = errorData.message || 'Unverified email - please verify your email';
          break;
        case 500:
          errorMessage = 'Server error - please try again later';
          break;
        default:
          errorMessage = errorData.message || 'An error occurred';
      }
    } else if (error.status) {
      switch (error.status) {
        case 400:
          errorMessage = 'Bad request';
          break;
        case 401:
          errorMessage = 'Unauthorized - please login again';
          break;
        case 403:
          errorMessage = 'Forbidden - insufficient permissions';
          break;
        case 404:
          errorMessage = 'Resource not found';
          break;
        case 409:
          errorMessage = 'Conflict - resource already exists';
          break;
        case 422:
          errorMessage = 'Unverified email - please verify your email';
          break;
        case 500:
          errorMessage = 'Server error - please try again later';
          break;
        default:
          errorMessage = 'An error occurred';
      }
    }

    return throwError(new Error(errorMessage));
  }
}
```

### 4. Authentication Guard

Create a guard to protect routes:

```typescript
// src/app/guards/auth.guard.ts
import { Injectable } from '@angular/core';
import { CanActivate, Router, UrlTree } from '@angular/router';
import { Observable } from 'rxjs';
import { AuthService } from '../services/auth.service';

@Injectable({
  providedIn: 'root',
})
export class AuthGuard implements CanActivate {
  constructor(
    private authService: AuthService,
    private router: Router
  ) {}

  canActivate(): Observable<boolean | UrlTree> | Promise<boolean | UrlTree> | boolean | UrlTree {
    if (this.authService.isLoggedIn()) {
      return true;
    } else {
      this.router.navigate(['/login']);
      return false;
    }
  }
}
```

### 5. Route Configuration

Configure routes with authentication guards:

```typescript
// src/app/app-routing.module.ts
import { NgModule } from '@angular/core';
import { RouterModule, Routes } from '@angular/router';
import { LoginComponent } from './components/login/login.component';
import { RegisterComponent } from './components/register/register.component';
import { HomeComponent } from './components/home/home.component';
import { ProfileComponent } from './components/profile/profile.component';
import { AuthGuard } from './guards/auth.guard';

const routes: Routes = [
  { path: '', redirectTo: '/home', pathMatch: 'full' },
  { path: 'login', component: LoginComponent },
  { path: 'register', component: RegisterComponent },
  { 
    path: 'home', 
    component: HomeComponent, 
    canActivate: [AuthGuard] 
  },
  { 
    path: 'profile', 
    component: ProfileComponent, 
    canActivate: [AuthGuard] 
  },
  { path: '**', redirectTo: '/home' },
];

@NgModule({
  imports: [RouterModule.forRoot(routes)],
  exports: [RouterModule],
})
export class AppRoutingModule {}
```

### 6. Login Component

Create a login component:

```typescript
// src/app/components/login/login.component.ts
import { Component, OnInit } from '@angular/core';
import { FormBuilder, FormGroup, Validators } from '@angular/forms';
import { Router } from '@angular/router';
import { AuthService } from '../../services/auth.service';

@Component({
  selector: 'app-login',
  templateUrl: './login.component.html',
  styleUrls: ['./login.component.css'],
})
export class LoginComponent implements OnInit {
  loginForm: FormGroup;
  isLoading = false;
  error: string | null = null;

  constructor(
    private formBuilder: FormBuilder,
    private authService: AuthService,
    private router: Router
  ) {
    this.loginForm = this.formBuilder.group({
      email: ['', [Validators.required, Validators.email]],
      password: ['', [Validators.required, Validators.minLength(8)]],
      accountType: ['buyer', [Validators.required]],
    });
  }

  ngOnInit(): void {
    // Redirect if already logged in
    if (this.authService.isLoggedIn()) {
      this.router.navigate(['/home']);
    }
  }

  onSubmit(): void {
    if (this.loginForm.valid) {
      this.isLoading = true;
      this.error = null;

      const { email, password, accountType } = this.loginForm.value;

      this.authService.login(email, password, accountType).subscribe({
        next: (user) => {
          this.isLoading = false;
          this.router.navigate(['/home']);
        },
        error: (error) => {
          this.isLoading = false;
          this.error = error.message;
        },
      });
    }
  }

  navigateToRegister(): void {
    this.router.navigate(['/register']);
  }
}
```

```html
<!-- src/app/components/login/login.component.html -->
<div class="login-container">
  <div class="login-card">
    <h2>Login</h2>
    
    <form [formGroup]="loginForm" (ngSubmit)="onSubmit()">
      <div class="form-group">
        <label for="email">Email</label>
        <input
          type="email"
          id="email"
          formControlName="email"
          class="form-control"
          [class.error]="loginForm.get('email')?.invalid && loginForm.get('email')?.touched"
        />
        <div *ngIf="loginForm.get('email')?.invalid && loginForm.get('email')?.touched" class="error-message">
          Please enter a valid email address
        </div>
      </div>

      <div class="form-group">
        <label for="password">Password</label>
        <input
          type="password"
          id="password"
          formControlName="password"
          class="form-control"
          [class.error]="loginForm.get('password')?.invalid && loginForm.get('password')?.touched"
        />
        <div *ngIf="loginForm.get('password')?.invalid && loginForm.get('password')?.touched" class="error-message">
          Password must be at least 8 characters long
        </div>
      </div>

      <div class="form-group">
        <label for="accountType">Account Type</label>
        <select
          id="accountType"
          formControlName="accountType"
          class="form-control"
        >
          <option value="buyer">Buyer</option>
          <option value="seller">Seller</option>
        </select>
      </div>

      <div *ngIf="error" class="error-message">
        {{ error }}
      </div>

      <button
        type="submit"
        class="btn btn-primary"
        [disabled]="loginForm.invalid || isLoading"
      >
        {{ isLoading ? 'Logging in...' : 'Login' }}
      </button>
    </form>

    <div class="register-link">
      <p>Don't have an account? <a (click)="navigateToRegister()">Register here</a></p>
    </div>
  </div>
</div>
```

```css
/* src/app/components/login/login.component.css */
.login-container {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  background-color: #f5f5f5;
}

.login-card {
  background: white;
  padding: 2rem;
  border-radius: 8px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
  width: 100%;
  max-width: 400px;
}

.login-card h2 {
  text-align: center;
  margin-bottom: 2rem;
  color: #333;
}

.form-group {
  margin-bottom: 1rem;
}

.form-group label {
  display: block;
  margin-bottom: 0.5rem;
  font-weight: 500;
  color: #555;
}

.form-control {
  width: 100%;
  padding: 0.75rem;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-size: 1rem;
  transition: border-color 0.3s;
}

.form-control:focus {
  outline: none;
  border-color: #007AFF;
  box-shadow: 0 0 0 2px rgba(0, 122, 255, 0.2);
}

.form-control.error {
  border-color: #dc3545;
}

.error-message {
  color: #dc3545;
  font-size: 0.875rem;
  margin-top: 0.25rem;
}

.btn {
  width: 100%;
  padding: 0.75rem;
  border: none;
  border-radius: 4px;
  font-size: 1rem;
  cursor: pointer;
  transition: background-color 0.3s;
}

.btn-primary {
  background-color: #007AFF;
  color: white;
}

.btn-primary:hover:not(:disabled) {
  background-color: #0056b3;
}

.btn-primary:disabled {
  background-color: #ccc;
  cursor: not-allowed;
}

.register-link {
  text-align: center;
  margin-top: 1rem;
}

.register-link a {
  color: #007AFF;
  text-decoration: none;
  cursor: pointer;
}

.register-link a:hover {
  text-decoration: underline;
}
```

### 7. App Component

Update the main app component to handle authentication state:

```typescript
// src/app/app.component.ts
import { Component, OnInit } from '@angular/core';
import { AuthService, User } from './services/auth.service';
import { Router } from '@angular/router';

@Component({
  selector: 'app-root',
  templateUrl: './app.component.html',
  styleUrls: ['./app.component.css'],
})
export class AppComponent implements OnInit {
  currentUser: User | null = null;
  isLoggedIn = false;

  constructor(
    private authService: AuthService,
    private router: Router
  ) {}

  ngOnInit(): void {
    // Subscribe to authentication state changes
    this.authService.currentUser$.subscribe((user) => {
      this.currentUser = user;
      this.isLoggedIn = !!user;
    });
  }

  logout(): void {
    this.authService.logout().subscribe({
      next: () => {
        this.router.navigate(['/login']);
      },
      error: (error) => {
        console.error('Logout error:', error);
        // Still navigate to login even if logout fails
        this.router.navigate(['/login']);
      },
    });
  }
}
```

```html
<!-- src/app/app.component.html -->
<nav class="navbar" *ngIf="isLoggedIn">
  <div class="nav-brand">
    <h1>Markt</h1>
  </div>
  <div class="nav-links">
    <a routerLink="/home" routerLinkActive="active">Home</a>
    <a routerLink="/profile" routerLinkActive="active">Profile</a>
  </div>
  <div class="nav-user">
    <span>Welcome, {{ currentUser?.username }}</span>
    <button (click)="logout()" class="btn btn-secondary">Logout</button>
  </div>
</nav>

<main>
  <router-outlet></router-outlet>
</main>
```

### 8. Email Verification Component

Create a component for email verification:

```typescript
// src/app/components/email-verification/email-verification.component.ts
import { Component, OnInit } from '@angular/core';
import { FormBuilder, FormGroup, Validators } from '@angular/forms';
import { AuthService } from '../../services/auth.service';
import { ActivatedRoute } from '@angular/router';

@Component({
  selector: 'app-email-verification',
  templateUrl: './email-verification.component.html',
  styleUrls: ['./email-verification.component.css'],
})
export class EmailVerificationComponent implements OnInit {
  verificationForm: FormGroup;
  isLoading = false;
  error: string | null = null;
  success: string | null = null;
  email: string = '';

  constructor(
    private formBuilder: FormBuilder,
    private authService: AuthService,
    private route: ActivatedRoute
  ) {
    this.verificationForm = this.formBuilder.group({
      verificationCode: ['', [Validators.required, Validators.pattern(/^\d{6}$/)]],
    });
  }

  ngOnInit(): void {
    // Get email from route params or query params
    this.email = this.route.snapshot.params['email'] || this.route.snapshot.queryParams['email'] || '';
  }

  sendVerificationCode(): void {
    if (!this.email) {
      this.error = 'Email address is required';
      return;
    }

    this.isLoading = true;
    this.error = null;

    this.authService.sendEmailVerification(this.email).subscribe({
      next: (response) => {
        this.isLoading = false;
        this.success = 'Verification code sent to your email';
      },
      error: (error) => {
        this.isLoading = false;
        this.error = error.message;
      },
    });
  }

  verifyEmail(): void {
    if (this.verificationForm.valid && this.email) {
      this.isLoading = true;
      this.error = null;

      const { verificationCode } = this.verificationForm.value;

      this.authService.verifyEmail(this.email, verificationCode).subscribe({
        next: (response) => {
          this.isLoading = false;
          this.success = 'Email verified successfully!';
          // Redirect to login or home
          setTimeout(() => {
            // Handle successful verification
          }, 2000);
        },
        error: (error) => {
          this.isLoading = false;
          this.error = error.message;
        },
      });
    }
  }
}
```

## Important Notes

### 1. Cookie Handling
- Always set `withCredentials: true` in HTTP requests
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
```typescript
// Test that session persists across browser refreshes
const testSessionPersistence = () => {
  // Login
  this.authService.login('test@example.com', 'password').subscribe(() => {
    // Refresh page
    window.location.reload();
    // Check if user is still logged in
    console.log('Session persisted:', this.authService.isLoggedIn());
  });
};
```

### 2. Test Cookie Handling
```typescript
// Test that cookies are sent with requests
const testCookieHandling = () => {
  this.authService.getCurrentUser().subscribe({
    next: (user) => {
      console.log('Profile data:', user);
    },
    error: (error) => {
      console.log('Cookie test failed:', error.message);
    },
  });
};
```

## Troubleshooting

### Common Issues

1. **Session not persisting**
   - Check if `withCredentials: true` is set in HTTP interceptor
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
   ```typescript
   console.log('Stored session:', localStorage.getItem('markt_user_session'));
   ```

3. **Test API Endpoints**
   - Use Postman or similar tool to test endpoints
   - Verify authentication works outside the app

## Security Considerations

1. **Local Storage**
   - Don't store sensitive data in localStorage
   - Use it only for user display data
   - Clear data on logout

2. **HTTPS**
   - Always use HTTPS in production
   - Cookies are only secure over HTTPS

3. **Session Management**
   - Implement proper logout functionality
   - Handle session expiration gracefully
   - Don't store passwords locally

4. **XSS Protection**
   - Sanitize user input
   - Use Angular's built-in XSS protection
   - Avoid using `innerHTML` with user data

This guide provides a complete implementation for Angular authentication with Flask-Login session management. The key difference from JWT-based auth is that you don't need to manually handle tokens - the HTTP client automatically manages session cookies.
