# Real-Time Socket Events Documentation

This document provides comprehensive information about all real-time socket events that the frontend should listen for and handle.

## Table of Contents

1. [Connection Setup](#connection-setup)
2. [Event Categories](#event-categories)
3. [Social Events](#social-events)
4. [Product Events](#product-events)
5. [Order Events](#order-events)
6. [Chat Events](#chat-events)
7. [Notification Events](#notification-events)
8. [Client-Side Implementation](#client-side-implementation)
9. [Error Handling](#error-handling)
10. [Performance Considerations](#performance-considerations)

## Connection Setup

### Socket.IO Connection

```javascript
import io from 'socket.io-client';

// Connect to specific namespaces for different features
const socialSocket = io('http://your-api-domain.com/social');
const chatSocket = io('http://your-api-domain.com/chat');
const ordersSocket = io('http://your-api-domain.com/orders');
const notificationsSocket = io('http://your-api-domain.com/notification');

// For backward compatibility, you can also use the default connection
const socket = io('http://your-api-domain.com', {
  transports: ['websocket', 'polling'],
  auth: {
    token: 'your-jwt-token' // Include user authentication
  }
});
```

### Room Joining

```javascript
// Join post-specific room (social namespace)
socialSocket.emit('join_post', { post_id: 'post_123' });

// Join product-specific room (social namespace)
socialSocket.emit('join_product', { product_id: 'product_456' });

// Join order-specific room (orders namespace)
ordersSocket.emit('join_order', { order_id: 'order_789' });

// Join chat room (chat namespace)
chatSocket.emit('join_chat', { room_id: 'chat_123' });
```

## Event Categories

### Immediate Events (No Throttling)
- `order_status_changed` - Order status updates
- `new_message` - Chat messages
- `payment_confirmed` - Payment confirmations
- `delivery_update` - Delivery status updates

### Throttled Events (Batched for Performance)
- `post_liked` / `post_unliked` - Post interactions
- `comment_reaction_added` / `comment_reaction_removed` - Comment reactions
- `request_upvoted` - Buyer request upvotes
- `review_added` / `review_upvoted` - Product reviews
- `typing_update` - Typing indicators

## Social Events

### Post Interactions

#### `post_liked`
**Triggered when:** A user likes a post
**Room:** `post_{post_id}`
**Data:**
```javascript
{
  "post_id": "post_123",
  "user_id": "user_456",
  "username": "john_doe",
  "like_count": 42,
  "timestamp": "2024-01-15T10:30:00Z"
}
```

#### `post_unliked`
**Triggered when:** A user unlikes a post
**Room:** `post_{post_id}`
**Data:**
```javascript
{
  "post_id": "post_123",
  "user_id": "user_456",
  "username": "john_doe",
  "like_count": 41,
  "timestamp": "2024-01-15T10:31:00Z"
}
```

### Comment Reactions

#### `comment_reaction_added`
**Triggered when:** A user adds a reaction to a comment
**Room:** `comment_{comment_id}`
**Data:**
```javascript
{
  "comment_id": 123,
  "user_id": "user_456",
  "username": "john_doe",
  "reaction_type": "heart",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

#### `comment_reaction_removed`
**Triggered when:** A user removes a reaction from a comment
**Room:** `comment_{comment_id}`
**Data:**
```javascript
{
  "comment_id": 123,
  "user_id": "user_456",
  "username": "john_doe",
  "reaction_type": "heart",
  "timestamp": "2024-01-15T10:31:00Z"
}
```

### Buyer Requests

#### `request_upvoted`
**Triggered when:** A user upvotes a buyer request
**Room:** `request_{request_id}`
**Data:**
```javascript
{
  "request_id": "request_123",
  "user_id": "user_456",
  "username": "john_doe",
  "upvote_count": 15,
  "timestamp": "2024-01-15T10:30:00Z"
}
```

## Product Events

### Product Reviews

#### `review_added`
**Triggered when:** A user adds a review to a product
**Room:** `product_{product_id}`
**Data:**
```javascript
{
  "product_id": "product_123",
  "review_id": "review_456",
  "user_id": "user_789",
  "username": "john_doe",
  "rating": 5,
  "review_count": 25,
  "avg_rating": 4.2,
  "is_verified": true,
  "timestamp": "2024-01-15T10:30:00Z"
}
```

#### `review_upvoted`
**Triggered when:** A user upvotes a product review
**Room:** `product_{product_id}`
**Data:**
```javascript
{
  "review_id": "review_456",
  "product_id": "product_123",
  "user_id": "user_789",
  "username": "john_doe",
  "upvotes": 8,
  "review_author_id": "user_101",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

## Order Events

### Order Status Changes

#### `order_status_changed`
**Triggered when:** Order status is updated
**Room:** `order_{order_id}`
**Data:**
```javascript
{
  "order_id": "order_123",
  "user_id": "user_456",
  "status": "shipped",
  "old_status": "confirmed",
  "metadata": {
    "order_number": "ORD-2024-001",
    "total": 99.99
  },
  "timestamp": "2024-01-15T10:30:00Z"
}
```

### Payment Confirmations

#### `payment_confirmed`
**Triggered when:** Payment is confirmed
**Room:** `order_{order_id}`
**Data:**
```javascript
{
  "payment_id": "payment_123",
  "order_id": "order_456",
  "user_id": "user_789",
  "amount": 99.99,
  "status": "completed",
  "transaction_id": "txn_123456",
  "metadata": {
    "method": "credit_card",
    "order_number": "ORD-2024-001"
  },
  "timestamp": "2024-01-15T10:30:00Z"
}
```

## Chat Events

### Messages

#### `new_message`
**Triggered when:** A new chat message is sent
**Room:** `chat_{room_id}`
**Namespace:** `/chat`
**Data:**
```javascript
{
  "message_id": "msg_123",
  "room_id": "chat_456",
  "sender_id": "user_789",
  "sender_name": "John Doe",
  "content": "Hello! Is this still available?",
  "message_type": "text",
  "timestamp": "2024-01-15T10:30:00Z"
}
```

### Typing Indicators

#### `typing_update`
**Triggered when:** User starts/stops typing
**Room:** `chat_{room_id}`
**Namespace:** `/chat`
**Data:**
```javascript
{
  "user_id": "user_123",
  "username": "john_doe",
  "is_typing": true,
  "timestamp": "2024-01-15T10:30:00Z"
}
```

## Client-Side Implementation

### Event Listeners Setup

```javascript
// Social events (use socialSocket)
socialSocket.on('post_liked', (data) => {
  updatePostLikeCount(data.post_id, data.like_count);
  showLikeNotification(data.username, data.post_id);
});

socialSocket.on('post_unliked', (data) => {
  updatePostLikeCount(data.post_id, data.like_count);
});

socialSocket.on('comment_reaction_added', (data) => {
  updateCommentReaction(data.comment_id, data.reaction_type, data.user_id, true);
});

socialSocket.on('comment_reaction_removed', (data) => {
  updateCommentReaction(data.comment_id, data.reaction_type, data.user_id, false);
});

socialSocket.on('review_added', (data) => {
  updateProductReviews(data.product_id, data);
  updateProductStats(data.product_id, data.review_count, data.avg_rating);
});

socialSocket.on('review_upvoted', (data) => {
  updateReviewUpvotes(data.review_id, data.upvotes);
});

// Order events (use ordersSocket)
ordersSocket.on('order_status_changed', (data) => {
  updateOrderStatus(data.order_id, data.status);
  showOrderNotification(data);
});

ordersSocket.on('payment_confirmed', (data) => {
  updatePaymentStatus(data.order_id, data.status);
  showPaymentNotification(data);
});

// Chat events (use chatSocket)
chatSocket.on('new_message', (data) => {
  addMessageToChat(data.room_id, data);
  playNotificationSound();
});

chatSocket.on('typing_update', (data) => {
  updateTypingIndicator(data.room_id, data.user_id, data.is_typing);
});
```

### Room Management

```javascript
class SocketRoomManager {
  constructor() {
    this.activeRooms = new Set();
  }

  joinPostRoom(postId) {
    const roomName = `post_${postId}`;
    if (!this.activeRooms.has(roomName)) {
      socket.emit('join_post', { post_id: postId });
      this.activeRooms.add(roomName);
    }
  }

  leavePostRoom(postId) {
    const roomName = `post_${postId}`;
    if (this.activeRooms.has(roomName)) {
      socket.emit('leave_post', { post_id: postId });
      this.activeRooms.delete(roomName);
    }
  }

  joinProductRoom(productId) {
    const roomName = `product_${productId}`;
    if (!this.activeRooms.has(roomName)) {
      socket.emit('join_product', { product_id: productId });
      this.activeRooms.add(roomName);
    }
  }

  joinOrderRoom(orderId) {
    const roomName = `order_${orderId}`;
    if (!this.activeRooms.has(roomName)) {
      socket.emit('join_order', { order_id: orderId });
      this.activeRooms.add(roomName);
    }
  }
}
```

### Optimistic Updates

```javascript
// Example: Optimistic like update
function handlePostLike(postId) {
  // Optimistic update
  const currentCount = getPostLikeCount(postId);
  updatePostLikeCount(postId, currentCount + 1);
  
  // API call
  api.likePost(postId)
    .then(response => {
      // Success - real-time event will confirm the update
      console.log('Post liked successfully');
    })
    .catch(error => {
      // Rollback optimistic update on failure
      updatePostLikeCount(postId, currentCount);
      showError('Failed to like post');
    });
}
```

## Error Handling

### Connection Errors

```javascript
socket.on('connect_error', (error) => {
  console.error('Socket connection failed:', error);
  showConnectionError();
});

socket.on('disconnect', (reason) => {
  console.log('Socket disconnected:', reason);
  if (reason === 'io server disconnect') {
    // Server disconnected, try to reconnect
    socket.connect();
  }
});

socket.on('reconnect', (attemptNumber) => {
  console.log('Socket reconnected after', attemptNumber, 'attempts');
  // Rejoin necessary rooms
  rejoinActiveRooms();
});
```

### Event Error Handling

```javascript
// Wrap event handlers with error handling
function safeEventHandler(handler) {
  return (data) => {
    try {
      handler(data);
    } catch (error) {
      console.error('Error handling socket event:', error);
      // Log to monitoring service
      logError('socket_event_error', { error, data });
    }
  };
}

// Use safe event handlers
socket.on('post_liked', safeEventHandler((data) => {
  updatePostLikeCount(data.post_id, data.like_count);
}));
```

## Performance Considerations

### Event Throttling

The backend implements throttling for high-frequency events. Frontend should:

1. **Debounce UI Updates**: Don't update UI for every event
2. **Batch Updates**: Collect multiple events and update UI in batches
3. **Use RequestAnimationFrame**: For smooth UI updates

```javascript
class EventBatcher {
  constructor() {
    this.pendingUpdates = new Map();
    this.isScheduled = false;
  }

  addUpdate(key, updateFn) {
    this.pendingUpdates.set(key, updateFn);
    this.scheduleUpdate();
  }

  scheduleUpdate() {
    if (!this.isScheduled) {
      this.isScheduled = true;
      requestAnimationFrame(() => {
        this.processUpdates();
      });
    }
  }

  processUpdates() {
    this.pendingUpdates.forEach((updateFn, key) => {
      try {
        updateFn();
      } catch (error) {
        console.error('Error processing update:', error);
      }
    });
    this.pendingUpdates.clear();
    this.isScheduled = false;
  }
}

const eventBatcher = new EventBatcher();

// Use batched updates
socket.on('post_liked', (data) => {
  eventBatcher.addUpdate(`post_${data.post_id}`, () => {
    updatePostLikeCount(data.post_id, data.like_count);
  });
});
```

### Memory Management

```javascript
// Clean up event listeners when components unmount
class SocketEventManager {
  constructor() {
    this.listeners = new Map();
  }

  addListener(event, handler) {
    socket.on(event, handler);
    this.listeners.set(event, handler);
  }

  removeListener(event) {
    const handler = this.listeners.get(event);
    if (handler) {
      socket.off(event, handler);
      this.listeners.delete(event);
    }
  }

  cleanup() {
    this.listeners.forEach((handler, event) => {
      socket.off(event, handler);
    });
    this.listeners.clear();
  }
}
```

## Testing Socket Events

### Mock Socket for Testing

```javascript
// Mock socket for unit tests
class MockSocket {
  constructor() {
    this.listeners = new Map();
    this.emitHistory = [];
  }

  on(event, handler) {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, []);
    }
    this.listeners.get(event).push(handler);
  }

  emit(event, data) {
    this.emitHistory.push({ event, data });
  }

  // Simulate receiving an event
  simulateEvent(event, data) {
    const handlers = this.listeners.get(event) || [];
    handlers.forEach(handler => handler(data));
  }

  // Clear history
  clear() {
    this.emitHistory = [];
  }
}
```

### Integration Tests

```javascript
// Example integration test
describe('Socket Events', () => {
  it('should update post like count when post_liked event is received', () => {
    const mockSocket = new MockSocket();
    const postId = 'post_123';
    
    // Setup component with mock socket
    const component = render(<PostComponent postId={postId} socket={mockSocket} />);
    
    // Simulate post_liked event
    mockSocket.simulateEvent('post_liked', {
      post_id: postId,
      like_count: 42,
      user_id: 'user_456',
      username: 'john_doe'
    });
    
    // Assert UI was updated
    expect(screen.getByText('42')).toBeInTheDocument();
  });
});
```

## Best Practices

1. **Always handle connection errors gracefully**
2. **Use optimistic updates for better UX**
3. **Implement proper cleanup when components unmount**
4. **Batch UI updates for performance**
5. **Test socket events thoroughly**
6. **Monitor socket connection health**
7. **Use namespaces to organize events**
8. **Implement retry logic for failed connections**

## Troubleshooting

### Common Issues

1. **Events not received**: Check if room is joined correctly
2. **Connection drops**: Implement automatic reconnection
3. **Memory leaks**: Ensure proper cleanup of event listeners
4. **Performance issues**: Use event batching and throttling

### Debug Mode

```javascript
// Enable debug logging
socket.on('connect', () => {
  console.log('Socket connected with ID:', socket.id);
});

socket.onAny((eventName, ...args) => {
  console.log('Received event:', eventName, args);
});
```

---

This documentation should help frontend developers implement real-time features effectively. For additional support, refer to the Socket.IO documentation or contact the backend team. 