# 🎫 Helpdesk Management

| | |
|---|---|
| **Author** | ERP Addons |
| **Website** | https://www.erp-addons.com |
| **Version** | 19.0.1.0.0 |
| **License** | OPL-1 |
| **Odoo** | 19.0 |

---

# 📖 Overview

**Helpdesk Management** provides a complete ticket management system for
handling customer support requests in Odoo.

Customers can create support tickets from the website, while support teams
can manage those tickets from the Odoo backend.

The module includes ticket stages, teams, categories, tags, customer
communication, portal access, ratings, task creation, ticket merging, and a
helpdesk dashboard.

---

# 🚀 Key Features

## 🎫 Helpdesk Ticket Management

Create and manage customer support tickets from the Odoo backend.

Tickets can contain information such as:

- Customer.
- Subject.
- Description.
- Priority.
- Helpdesk team.
- Assigned user.
- Ticket type.
- Category.
- Products.
- Tags.
- Stage.

Tickets can be managed using different views such as:

- List.
- Form.
- Kanban.
- Calendar.
- Activity.
- Pivot.
- Graph.

---

## 🌐 Website Ticket Creation

Customers can create support tickets directly from the website.

The website form can collect:

- Customer name.
- Email.
- Phone.
- Company.
- Subject.
- Description.
- Priority.
- Ticket type.
- Category.
- Product.
- Attachments.

After submission, the ticket is automatically created in Odoo.

---

## 👤 Customer Portal

Customers can access their support tickets through the website portal.

They can view ticket information and follow the progress of their requests.

Customers can also provide a rating and review for their ticket.

---

## ⭐ Customer Rating

Customers can rate completed support tickets from the website.

The rating can include:

- Rating value.
- Customer review.

This helps support teams collect feedback about their service.

---

## 👥 Helpdesk Teams

Create teams to organize support work.

Each team can have:

- Team leader.
- Team members.
- Email address.
- Related project.
- Task creation option.

Tickets can be assigned to the appropriate support team and team members.

---

## 🔄 Ticket Stages

Tickets can move through configurable stages.

The module provides stages such as:

```text
Inbox
Draft
In Progress
Canceled
Done
Closed
```

You can create your own stages and configure them as:

- Starting stage.
- Closing stage.
- Cancel stage.
- Folded Kanban stage.

Email templates can also be connected to stages for automatic communication.

---

## 🏷️ Ticket Categories, Types and Tags

Organize tickets using:

### Categories

Use categories to classify support requests.

### Types

Create different ticket types for different kinds of support requests.

### Tags

Add tags to tickets for quick identification and filtering.

---

## 📊 Helpdesk Dashboard

The module provides a dashboard for viewing ticket statistics.

The dashboard can show ticket counts for different stages, including:

- New tickets.
- In Progress.
- Canceled.
- Done.
- Closed.

Statistics can be viewed for different time periods, including:

- Current tickets.
- Last 7 days.
- Last 30 days.
- Last year.

Tickets can be opened directly from the dashboard statistics.

---

## 🔎 Ticket Search and Grouping

Users can search tickets using:

- Ticket number.
- Ticket subject.

Tickets can also be grouped by:

- Assigned user.
- Ticket stage.
- Ticket type.

This makes it easier to find and organize support requests.

---

## 📎 Ticket Attachments

Customers can attach files when creating a ticket from the website.

The uploaded files are stored with the related helpdesk ticket.

---

## 👨‍💻 Create Tasks from Tickets

Helpdesk tickets can be connected with Odoo projects and tasks.

When enabled in the settings, users can create tasks directly from a ticket.

This is useful when a support request requires development, technical work,
or other project activities.

---

## 💰 Ticket Time Billing and Invoicing

The module supports creating invoices from billable work related to a ticket.

When tasks contain billable work, the system can calculate the applicable
hours and create an invoice for the customer.

This is useful for support services that are charged based on work performed.

---

## 🔀 Merge Tickets

Multiple support tickets can be combined when they are related to the same
issue.

You can:

- Merge ticket information into an existing ticket.
- Create a new ticket from the selected tickets.
- Enter a merge reason.
- Keep the information from the original tickets.

This helps reduce duplicate support requests.

---

## ♻️ Duplicate Ticket Management

The module allows users to identify duplicate tickets.

A ticket can be linked to another ticket as its duplicate.

Users can also choose a target stage when marking a ticket as a duplicate.

---

## 📧 Email Notifications

Email templates can be used for ticket communication.

The module can send notifications when tickets are assigned or moved through
configured stages.

This helps customers and support users stay informed about ticket updates.

---

## ⏰ Automatic Ticket Closing

Tickets can be automatically closed after a configured number of days.

The feature can be enabled from Helpdesk settings.

Example:

```text
Auto Close Ticket: Enabled
Number of Days: 30
Closing Stage: Closed
```

Tickets older than the configured period can then be moved to the closing
stage automatically.

---

## ⚙️ Helpdesk Configuration

The module provides settings for controlling helpdesk behavior.

Available options include:

- Create Tasks.
- Show Category.
- Product on Website.
- Auto Close Ticket.
- Number of Days.
- Closing Stage.
- Reply Template.
- Helpdesk Menu.
- Duplicate Ticket Tracking.
- Duplicate Ticket Stage.

---

# ⚙️ Installation

1. Copy the **helpdesk_management** module into your Odoo addons directory.
2. Restart the Odoo server.
3. Update the Apps List.

**📍 Menu Navigation**

`Apps → Update Apps List`

4. Search for **Helpdesk Management**.
5. Click **Install**.

The module depends on:

```text
base
website
project
sale_project
hr_timesheet
mail
contacts
```

---

# 📖 Usage

## 🎫 Create a Ticket from Backend

1. Open **Helpdesk**.
2. Go to the ticket list.
3. Click **New**.
4. Select the customer.
5. Enter the subject and description.
6. Select the team and assigned user.
7. Set the priority, type, category, and tags if required.
8. Save the ticket.

The ticket can then be moved through the configured stages.

---

## 🌐 Create a Ticket from Website

1. Open the website.
2. Open the Helpdesk ticket form.
3. Enter customer information.
4. Enter the ticket subject and description.
5. Select the required type, category, or product.
6. Add attachments if required.
7. Submit the form.

The system creates a helpdesk ticket automatically.

---

## 👥 Configure a Helpdesk Team

1. Open **Helpdesk → Configuration → Teams**.
2. Create a new team.
3. Enter the team name.
4. Select the team leader.
5. Add team members.
6. Select a related project if required.
7. Enable task creation if needed.
8. Save the team.

---

## 🔄 Configure Ticket Stages

1. Open **Helpdesk → Configuration → Stages**.
2. Create or edit a stage.
3. Set the sequence.
4. Choose whether it is a starting, closing, or cancel stage.
5. Optionally select an email template.
6. Save the stage.

---

## ⚙️ Configure Automatic Closing

1. Open **Helpdesk Settings**.
2. Enable **Auto Close Ticket**.
3. Enter the number of days.
4. Select the closing stage.
5. Save the settings.

---

# 🧩 How It Works

```text
Helpdesk Management
│
├── Website Ticket Form
├── Customer Portal
├── Helpdesk Tickets
├── Helpdesk Teams
├── Ticket Stages
├── Categories / Types / Tags
├── Ticket Search & Grouping
├── Customer Ratings
├── Attachments
├── Task Management
├── Ticket Billing
├── Ticket Merging
├── Duplicate Tickets
├── Email Notifications
├── Automatic Ticket Closing
└── Helpdesk Dashboard
```

---

# 📌 Changelog

## 19.0.1.0.0 — Initial Release 

- Added complete helpdesk ticket management.
- Added website ticket creation.
- Added customer portal support.
- Added helpdesk teams and team members.
- Added configurable ticket stages.
- Added ticket categories, types, and tags.
- Added helpdesk dashboard and ticket statistics.
- Added ticket search and grouping.
- Added customer rating and review.
- Added website ticket attachments.
- Added task creation from helpdesk tickets.
- Added ticket billing and invoice support.
- Added ticket merging.
- Added duplicate ticket management.
- Added email notifications and templates.
- Added automatic ticket closing.
- Added configurable helpdesk settings.
- Compatible with Odoo 19.

---


# 💬 Support

For questions, feature requests, or technical support, please visit:

🌐 **https://www.erp-addons.com**