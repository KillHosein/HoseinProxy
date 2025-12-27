# Template Structure Documentation

This directory contains the HTML templates for the HoseinProxy panel, organized for maintainability and scalability.

## Directory Structure

### `layouts/`
Contains the master layout files.
- `base.html`: The main layout used by all admin pages. Includes sidebar, navbar, and flash messages.

### `components/`
Reusable UI components.
- `sidebar.html`: The side navigation menu.
- `navbar.html`: The top navigation bar (toggle button, theme switch, user profile).

### `pages/`
The actual views rendered by Flask routes.

#### `admin/`
Protected pages for authenticated users.
- `dashboard.html`: Main overview.
- `settings.html`: System configuration.
- `users.html`: Admin user management.
- `firewall.html`: Blocked IP management.
- `reports.html`: Traffic reports.
- `system.html`: System status and updates.
- `tools.html`: Network tools (ping, traceroute).

#### `auth/`
Public pages for authentication.
- `login.html`: Login form.

## Design System

The templates use **Bootstrap 5 (RTL)** with a custom **Dark Mode** implementation.
- **Font**: Vazirmatn (CDN)
- **Icons**: FontAwesome 6 (CDN)
- **Theme**: Auto-detects system preference and saves to LocalStorage.

### Extending
To create a new admin page:
```html
{% extends "layouts/base.html" %}

{% block title %}Page Title{% endblock %}

{% block content %}
    <h1>Your Content</h1>
{% endblock %}
```
