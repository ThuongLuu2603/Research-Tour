---
name: analyze-requirements
description: Phân tích yêu cầu dự án OTA platform - xác định user stories, functional & non-functional requirements, constraints, dependencies. Dùng khi cần document requirements cho backend/frontend/database development.
---

# Analyze Requirements Skill

## Mục đích
Tạo comprehensive requirements document từ project description, xác định functional requirements (auth, pricing, booking, tour management, etc.), non-functional requirements (performance, security), constraints, và dependencies.

## Workflow

### 1. Requirements Gathering
- Phân tích project scope & description
- Xác định primary features (tours, bookings, payments, user management, etc.)
- Xác định user roles (customer, admin, operator, etc.)
- Xác định key workflows (search, book, manage, admin, etc.)

### 2. Functional Requirements
Phân loại by feature area:

**Tour Management:**
- Tour catalog with filtering (destination, date, price, duration, rating)
- Tour details view (itinerary, pricing, images, reviews)
- Search & discovery
- Favorites/wishlist

**Booking & Reservation:**
- Add to cart / booking flow
- Pricing calculation (base + taxes + discounts)
- Passenger details form
- Booking confirmation & status tracking

**Payment:**
- Payment methods (credit card, bank transfer, etc.)
- Payment status & reconciliation
- Invoice generation

**User Management:**
- Registration & authentication
- Profile management
- Booking history
- Preferences & notifications

**Admin Management:**
- Tour creation & management
- Inventory management
- Pricing management
- User & booking management
- Reports & analytics

### 3. Non-Functional Requirements
- **Performance:** API response times, search latency, concurrent users
- **Scalability:** Concurrent users, data growth, geographies
- **Security:** Authentication, authorization, data protection, PCI compliance
- **Reliability:** Uptime, data consistency, disaster recovery
- **Usability:** Mobile-responsive, accessibility, UX patterns
- **Maintainability:** Code quality, documentation, testing coverage

### 4. Constraints & Assumptions
- Tech stack (Python + FastAPI backend, TypeScript + React frontend, CockroachDB)
- Platform (Render hosting, CockroachDB Cloud)
- Third-party integrations (Google Sheets, scraper APIs, payment gateways)
- Timeline & resource constraints
- Budget constraints

### 5. External Dependencies
- Payment gateway API (Stripe, PayPal, etc.)
- Email service (SendGrid, etc.)
- Map service (Google Maps, etc.)
- Currency exchange rates
- Availability sync with suppliers

## Output Format

```markdown
# OTA Platform Requirements

## Executive Summary
[1-2 paragraphs overview]

## Functional Requirements

### Tour Management
- Requirement 1
- Requirement 2
...

### Booking & Reservation
...

### Payment
...

### User Management
...

### Admin Management
...

## Non-Functional Requirements
- Performance: [targets]
- Scalability: [targets]
- Security: [requirements]
- Reliability: [targets]
- Usability: [guidelines]

## Constraints & Assumptions
- Tech Stack: ...
- Platform: ...
- Integrations: ...
- Timeline: ...

## External Dependencies
- Payment APIs
- Email service
- Map services
- etc.

## Success Criteria
- All functional requirements implemented
- Performance targets met
- Security compliance achieved
- User acceptance testing passed

## Next Steps
- Database design phase
- Backend API development
- Frontend development
- QA testing
- Deployment
```

## Key Principles
1. **Be specific:** Use concrete examples instead of vague statements
2. **Identify priorities:** Mark must-have vs nice-to-have requirements
3. **Clarify ambiguities:** Ask for clarification if requirements are unclear
4. **Document assumptions:** Explicitly list what we're assuming
5. **Consider constraints:** Factor in tech stack, timeline, resources

## Tips
- Use user stories format: "As a [user], I want [feature], so that [benefit]"
- Group related requirements
- Validate requirements against existing codebase (api/, models.py)
- Cross-check with tech stack capabilities
- Identify potential conflicts or dependencies early

