// Service Worker for Push Notifications
self.addEventListener('push', function(event) {
    console.log('Push notification received:', event);
    
    let notificationData = {};
    
    if (event.data) {
        try {
            notificationData = event.data.json();
        } catch (e) {
            notificationData = {
                title: 'לייד חדש הגיע!',
                body: 'לייד חדש התקבל במערכת',
                icon: '/static/icon-192.png',
                badge: '/static/badge-72.png'
            };
        }
    }
    
    const options = {
        body: notificationData.body || 'לייד חדש התקבל במערכת',
        icon: notificationData.icon || '/static/icon-192.png',
        badge: notificationData.badge || '/static/badge-72.png',
        vibrate: [200, 100, 200],
        tag: 'new-lead',
        requireInteraction: true,
        actions: [
            {
                action: 'view',
                title: 'צפה בלייד',
                icon: '/static/view-icon.png'
            },
            {
                action: 'dismiss',
                title: 'סגור',
                icon: '/static/close-icon.png'  
            }
        ],
        data: {
            url: '/campaign-manager',
            leadId: notificationData.leadId,
            timestamp: Date.now()
        }
    };
    
    event.waitUntil(
        self.registration.showNotification(
            notificationData.title || 'לייד חדש הגיע!',
            options
        )
    );
});

// Handle notification click
self.addEventListener('notificationclick', function(event) {
    console.log('Notification clicked:', event);
    
    event.notification.close();
    
    if (event.action === 'view') {
        // Open the campaign manager page
        event.waitUntil(
            clients.openWindow('/campaign-manager')
        );
    } else if (event.action === 'dismiss') {
        // Just close the notification
        return;
    } else {
        // Default click - open the app
        event.waitUntil(
            clients.openWindow('/campaign-manager')
        );
    }
});

// Handle notification close
self.addEventListener('notificationclose', function(event) {
    console.log('Notification closed:', event);
});