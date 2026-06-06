---
name: develop-backend
description: Phát triển backend APIs cho OTA platform - implement FastAPI endpoints, models, business logic, integrations. Dùng khi cần phát triển API routes, SQLAlchemy models, tích hợp services.
---

# Develop Backend Skill

## Mục đích
Implement backend APIs, models, business logic cho OTA platform dựa trên schema design và requirements.

## Project Structure
```
backend/
├── api/
│   ├── auth.py          # Authentication endpoints
│   ├── tours.py         # Tour management endpoints
│   ├── bookings.py      # Booking endpoints
│   ├── payments.py      # Payment endpoints
│   ├── admin.py         # Admin endpoints
│   ├── users.py         # User endpoints
│   └── [other routes]
├── models.py            # SQLAlchemy ORM models
├── database.py          # Database initialization & session
├── config.py            # Configuration & settings
├── main.py              # FastAPI app initialization
├── requirements.txt     # Python dependencies
├── migrations/          # Alembic migrations
└── tests/               # Unit & integration tests
```

## Workflow

### 1. Model Definition (SQLAlchemy)
```python
from sqlalchemy import Column, String, Integer, Float, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
import uuid
from datetime import datetime

class Tour(Base):
    __tablename__ = "tours"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(255), nullable=False)
    description = Column(String, nullable=True)
    destination = Column(String(255), nullable=False)
    duration_days = Column(Integer, nullable=False)
    base_price = Column(Float, nullable=False)
    rating = Column(Float, nullable=True)
    review_count = Column(Integer, default=0)
    
    # Relationships
    bookings = relationship("Booking", back_populates="tour")
    reviews = relationship("Review", back_populates="tour")
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

### 2. API Endpoints (FastAPI)
```python
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel

router = APIRouter(prefix="/api/tours", tags=["tours"])

class TourResponse(BaseModel):
    id: str
    title: str
    destination: str
    duration_days: int
    base_price: float
    
    class Config:
        from_attributes = True

@router.get("/", response_model=list[TourResponse])
async def list_tours(
    destination: str | None = None,
    category: str | None = None,
    db: Session = Depends(get_db)
):
    """List tours with optional filtering"""
    query = db.query(Tour)
    if destination:
        query = query.filter(Tour.destination == destination)
    if category:
        query = query.filter(Tour.category == category)
    return query.all()

@router.get("/{tour_id}", response_model=TourResponse)
async def get_tour(tour_id: str, db: Session = Depends(get_db)):
    """Get single tour"""
    tour = db.query(Tour).filter(Tour.id == tour_id).first()
    if not tour:
        raise HTTPException(status_code=404, detail="Tour not found")
    return tour
```

### 3. Business Logic
Implement complex operations in service classes or routers:
- **Pricing calculation:** Apply base price + discounts + taxes
- **Booking validation:** Check availability, passenger limits
- **Payment processing:** Integrate with payment gateway
- **Status transitions:** Booking status workflow (pending → confirmed → completed)
- **Notifications:** Send confirmation emails

### 4. Database Operations
```python
# CRUD operations
def create_booking(booking_data: BookingCreate, db: Session):
    booking = Booking(**booking_data.dict())
    db.add(booking)
    db.commit()
    db.refresh(booking)
    return booking

def get_user_bookings(user_id: str, db: Session):
    return db.query(Booking).filter(Booking.user_id == user_id).all()

def update_booking_status(booking_id: str, status: str, db: Session):
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if booking:
        booking.status = status
        db.commit()
    return booking
```

### 5. Error Handling & Validation
- Use Pydantic models for request validation
- Return proper HTTP status codes (400, 401, 403, 404, 500)
- Log errors with context (user_id, operation, stack trace)
- Implement retry logic for external API calls

### 6. Testing
```python
# Unit test example
async def test_get_tour(client, db):
    # Create test tour
    tour = Tour(title="Test", destination="Hanoi", duration_days=2, base_price=100)
    db.add(tour)
    db.commit()
    
    # Test GET endpoint
    response = client.get(f"/api/tours/{tour.id}")
    assert response.status_code == 200
    assert response.json()["title"] == "Test"
```

## Key Patterns

| Pattern | Use Case | Example |
|---------|----------|---------|
| **CRUD** | Basic resource operations | GET/POST/PUT/DELETE tours |
| **Filtering** | Search & filter | GET /tours?destination=Hanoi&price_max=1000 |
| **Pagination** | Large result sets | GET /tours?page=1&limit=20 |
| **Status Workflow** | State transitions | POST /bookings/{id}/confirm |
| **Async Operations** | Long-running tasks | Queue booking confirmations |
| **Transaction** | Multi-step operations | Booking + Payment + Notification |

## Performance Tips
- Use SQLAlchemy relationships wisely (lazy loading vs eager loading)
- Add database indexes for common queries
- Batch inserts for multiple records
- Cache frequently accessed data (tours list, pricing rules)
- Use connection pooling (CockroachDB pool management)

## Integration Points
- **External APIs:** Payment gateway, email service, map service
- **Internal services:** Pricing engine, search, analytics
- **Message queue:** For async operations (confirmations, notifications)
- **Caching:** Redis for session data, tour catalog

## Code Style
- Follow FastAPI best practices
- Use dependency injection for database sessions
- Implement comprehensive logging
- Write docstrings for all endpoints & functions
- Use type hints (Python 3.10+)

