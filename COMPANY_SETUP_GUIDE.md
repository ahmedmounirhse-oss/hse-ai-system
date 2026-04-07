# HSE AI Platform - Multi-Company Setup Guide

## Overview
The HSE AI Platform now supports multiple companies with isolated data and separate admin access. Each company can have its own safety reports, risk assessments, and incident investigations while maintaining data privacy.

## Company Structure

### Available Companies
- **Default Company**: Demo and testing environment
- **Company 1-4**: Production environments for client testing

### URLs for Each Company
- Default: `/?company=default`
- Company 1: `/?company=company1`
- Company 2: `/?company=company2`
- Company 3: `/?company=company3`
- Company 4: `/?company=company4`

## User Access Levels

### Public Access (No Login Required)
Workers can access these features without authentication:
- 📋 **Safety Observation & Reporting**
- ⚠️ **Risk Assessment**
- 🔍 **Incident Investigation**

### Admin Access (Login Required)
Dashboard access requires company-specific admin credentials:
- 📊 **Dashboard** (KPI Reports, Analytics, etc.)

## Admin Credentials

Each company has its own admin account:

| Company | Username | Password |
|---------|----------|----------|
| Default | `admin_default` | `admin123_default` |
| Company 1 | `admin_company1` | `admin123_company1` |
| Company 2 | `admin_company2` | `admin123_company2` |
| Company 3 | `admin_company3` | `admin123_company3` |
| Company 4 | `admin_company4` | `admin123_company4` |

## How to Use

### For Workers:
1. Visit the company URL (e.g., `/?company=company1`)
2. Access safety reporting, risk assessment, and incident investigation
3. All data is automatically associated with the company

### For Admins:
1. Visit the company URL (e.g., `/?company=company1`)
2. Click "📊 Dashboard" in the navigation
3. Login with company-specific admin credentials
4. Access KPI reports, analytics, and management tools

### Company Selection:
- Visit `/companies` to see all available companies
- Click on any company to access its environment

## Data Isolation
- Each company's data is completely isolated
- Reports, assessments, and investigations are company-specific
- Admin access is restricted to the specific company

## Features Available Per Company
- ✅ Safety observation reporting
- ✅ AI-powered risk assessment with EGPC matrix
- ✅ Incident investigation with 5 Whys analysis
- ✅ Comprehensive KPI dashboard (admin only)
- ✅ Real-time analytics and predictions
- ✅ Printable reports

## Technical Implementation
- Company-based URL parameters for data isolation
- Session-based admin authentication
- SQLite database with company_id foreign keys
- Automatic company creation for new environments

## Support
For technical support or questions about the multi-company setup, contact the development team.