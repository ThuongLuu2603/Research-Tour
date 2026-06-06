---
name: design-database
description: Thiết kế schema database cho OTA platform dựa trên requirements - tạo entities, relationships, indexes, migrations. Dùng khi cần schema SQL, data models, database architecture.
---

# Design Database Skill

## Mục đích
Tạo comprehensive database schema design từ requirements, bao gồm entities, relationships, normalization, indexes, constraints, migrations.

## Workflow

### 1. Entity Identification
Từ requirements, xác định main entities:
- **Tour:** tour_id, title, description, destination, duration, pricing_tiers
- **Booking:** booking_id, user_id, tour_id, status, total_price, passengers
- **User:** user_id, email, name, role, phone, preferences
- **Payment:** payment_id, booking_id, status, method, amount, transaction_id
- **PricingSegment:** segment_id, name, rules (date-based, occupancy-based, discount rules)
- **Review:** review_id, tour_id, user_id, rating, comment
- **etc.**

### 2. Relationship Design
- One-to-Many: User → Bookings, Tour → Bookings, Booking → Payments
- Many-to-Many: Tour ↔ Tags, User ↔ Favorites
- Self-referencing: Category → Parent Category

### 3. Normalization
- **3NF:** Eliminate transitive dependencies
- **Denormalization:** Consider for performance (e.g., cache pricing, review stats)
- **Partitioning:** Partition large tables (Bookings by date, Tours by destination)

### 4. Index Strategy
- **Primary keys:** All tables
- **Foreign keys:** For joins (booking.tour_id, booking.user_id)
- **Search columns:** tour.destination, tour.category, booking.status
- **Time-based:** booking.created_at for range queries
- **Composite indexes:** (user_id, created_at) for user bookings list

### 5. CockroachDB Specific
- **No SERIAL:** Use UUID or auto-generated IDs
- **No CASCADE DELETE:** Implement cascade logic in application
- **Distributed:** Consider zone constraints, interleaving for locality
- **JSON columns:** For flexible fields (tour extras, passenger details)
- **CRDB indexes:** Can use partial indexes, expression indexes

### 6. Constraints & Validation
- NOT NULL constraints
- UNIQUE constraints (email, booking_reference)
- CHECK constraints (status IN (...), rating BETWEEN 0 AND 5)
- FOREIGN KEY constraints (with ON DELETE rules)

### 7. Migration Strategy
- Initial schema (v1)
- Incremental migrations for new features
- Data backfill strategy for new columns
- Rollback procedures

## Output Format

```markdown
# OTA Platform Database Schema

## Entity-Relationship Diagram
[ASCII ERD or description]

## Table Definitions

### tours
```sql
CREATE TABLE tours (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  title VARCHAR(255) NOT NULL,
  description TEXT,
  destination VARCHAR(255) NOT NULL,
  duration_days INT NOT NULL,
  base_price DECIMAL(10,2) NOT NULL,
  category VARCHAR(100),
  rating DECIMAL(3,2),
  review_count INT DEFAULT 0,
  max_capacity INT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  
  UNIQUE(title, destination),
  CHECK (base_price > 0),
  CHECK (duration_days > 0)
);
```

### bookings
```sql
CREATE TABLE bookings (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL REFERENCES users(id),
  tour_id UUID NOT NULL REFERENCES tours(id),
  status VARCHAR(20) NOT NULL DEFAULT 'pending',
  total_price DECIMAL(10,2) NOT NULL,
  passenger_count INT NOT NULL,
  booking_date DATE NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  
  CHECK (passenger_count > 0),
  CHECK (total_price >= 0),
  INDEX (user_id, created_at),
  INDEX (tour_id, booking_date),
  INDEX (status)
);
```

### [other tables...]
```

## Indexes
- Primary keys on all tables
- Foreign keys for joins
- Search columns (destination, category, status)
- Composite indexes for common queries

## Constraints
- NOT NULL, UNIQUE, CHECK, FOREIGN KEY
- Validation rules (price > 0, rating 0-5, etc.)

## CockroachDB Notes
- Using UUID for distributed PKs
- JSON columns for flexible data (extras, preferences)
- Partial indexes for status-based queries
- No CASCADE DELETE (implement in app)

## Migration Plan
- v1: Initial schema (users, tours, bookings, payments)
- v2: Add pricing_segments, reviews
- v3: Add user preferences, favorites
- etc.

## Data Dictionary
[Column-level documentation]

## Performance Considerations
- Partition bookings by booking_date
- Archive old completed bookings
- Denormalize review stats on tours table
```

## Key Principles
1. **Normalization first:** Start 3NF, denormalize only if needed for perf
2. **Index strategically:** Index for common queries, not every column
3. **CockroachDB aware:** Use CRDB-specific features (UUID, JSON, zones)
4. **Migration-ready:** Design with future changes in mind
5. **Constraint coverage:** Validate data at database layer

## Tips
- Use existing models.py as reference for CockroachDB compatibility
- Consider foreign key cardinality (1:1, 1:N, M:N)
- Plan for temporal data (timestamps, soft deletes, audit logs)
- Document constraint rationale (e.g., why CHECK rating BETWEEN 0 AND 5)
- Validate index strategy against query patterns from requirements

