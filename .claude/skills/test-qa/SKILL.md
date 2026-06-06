---
name: test-qa
description: Kiểm tra chất lượng backend & frontend - verify requirements coverage, API contracts, database integrity, UI correctness. Dùng khi cần test APIs, database, UI/UX, integration.
---

# Test QA Skill

## Mục đích
Comprehensive testing coverage: unit tests, integration tests, API contract testing, database integrity, UI/UX validation.

## Testing Pyramid

```
        UI/E2E Tests (10%)
       Integration Tests (30%)
     Unit Tests (60%)
```

## 1. Unit Tests

### Backend (Python/FastAPI)
```python
# tests/test_api_tours.py
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

@pytest.fixture
def sample_tour():
    return {
        "title": "Paris Tour",
        "destination": "Paris",
        "duration_days": 3,
        "base_price": 1000.0,
    }

def test_get_tours(sample_tour, db):
    # Create test tour
    tour = Tour(**sample_tour)
    db.add(tour)
    db.commit()
    
    # Test GET endpoint
    response = client.get("/api/tours/")
    assert response.status_code == 200
    assert len(response.json()) > 0
    assert response.json()[0]["title"] == "Paris Tour"

def test_create_booking(sample_tour, db):
    booking_data = {
        "tour_id": "tour-123",
        "user_id": "user-456",
        "passenger_count": 2,
        "total_price": 2000.0,
    }
    
    response = client.post("/api/bookings", json=booking_data)
    assert response.status_code == 201
    assert response.json()["status"] == "pending"

def test_invalid_booking(db):
    # Test invalid passenger count
    booking_data = {
        "tour_id": "tour-123",
        "user_id": "user-456",
        "passenger_count": -1,  # Invalid
        "total_price": 2000.0,
    }
    
    response = client.post("/api/bookings", json=booking_data)
    assert response.status_code == 400
```

### Frontend (React/TypeScript)
```typescript
// tests/components/TourCard.test.tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { TourCard } from "@/components/TourCard";

describe("TourCard", () => {
  it("renders tour information", () => {
    const tour = {
      id: "1",
      title: "Paris Tour",
      destination: "Paris",
      basePrice: 1000,
      durationDays: 3,
    };
    
    render(<TourCard tour={tour} onBook={jest.fn()} />);
    
    expect(screen.getByText("Paris Tour")).toBeInTheDocument();
    expect(screen.getByText(/Paris/)).toBeInTheDocument();
    expect(screen.getByText(/\$1000/)).toBeInTheDocument();
  });

  it("calls onBook when button clicked", async () => {
    const onBook = jest.fn();
    const tour = { id: "1", title: "Tour", ... };
    
    render(<TourCard tour={tour} onBook={onBook} />);
    
    await userEvent.click(screen.getByText("Book Now"));
    expect(onBook).toHaveBeenCalledWith("1");
  });
});
```

## 2. Integration Tests

### API Contract Testing
```python
# tests/test_api_contracts.py
from pydantic import BaseModel

class TourResponse(BaseModel):
    id: str
    title: str
    destination: str
    basePrice: float
    durationDays: int

def test_tour_response_contract():
    response = client.get("/api/tours/tour-123")
    data = response.json()
    
    # Validate response matches contract
    tour = TourResponse(**data)
    assert tour.id == "tour-123"
    assert tour.basePrice > 0
```

### Database Integrity
```python
def test_booking_database_integrity(db):
    # Create tour & user
    tour = Tour(id="tour-1", title="Tour", ...)
    user = User(id="user-1", email="user@example.com")
    db.add_all([tour, user])
    db.commit()
    
    # Create booking
    booking = Booking(
        id="booking-1",
        tour_id="tour-1",
        user_id="user-1",
        status="pending"
    )
    db.add(booking)
    db.commit()
    
    # Verify relationships work
    stored_booking = db.query(Booking).get("booking-1")
    assert stored_booking.tour.title == "Tour"
    assert stored_booking.user.email == "user@example.com"
```

### Frontend → Backend Integration
```typescript
// tests/integration/booking-flow.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import { BookingPage } from "@/pages/BookingPage";

// Mock API
jest.mock("@/lib/api", () => ({
  getTours: jest.fn(() => Promise.resolve([...])),
  createBooking: jest.fn(() => Promise.resolve({ id: "booking-1" })),
}));

test("booking flow from search to confirmation", async () => {
  render(<BookingPage />);
  
  // Select tour
  await userEvent.click(screen.getByText("Book Now"));
  
  // Fill form
  await userEvent.type(screen.getByLabelText("Email"), "user@example.com");
  await userEvent.type(screen.getByLabelText("Passengers"), "2");
  
  // Submit
  await userEvent.click(screen.getByText("Confirm Booking"));
  
  // Verify confirmation
  await waitFor(() => {
    expect(screen.getByText(/Booking Confirmed/)).toBeInTheDocument();
  });
});
```

## 3. Requirements Coverage Matrix

Create matrix tracking which requirements are tested:

| Requirement | Unit Test | Integration Test | E2E Test | Status |
|------------|-----------|-----------------|----------|--------|
| Tour search | ✅ | ✅ | ✅ | PASS |
| Booking creation | ✅ | ✅ | ✅ | PASS |
| Payment processing | ✅ | ✅ | ✅ | PASS |
| User authentication | ✅ | ✅ | ✅ | PASS |
| Admin management | ✅ | ⚠️ | ❌ | PARTIAL |

## 4. Bug Documentation

| Bug ID | Title | Severity | Reproduction | Status |
|--------|-------|----------|--------------|--------|
| BUG-001 | Price calculation wrong for discounts | High | Book tour with 10%+ discount | OPEN |
| BUG-002 | Mobile layout broken on iPhone 12 | Medium | View on iPhone 12 | OPEN |
| BUG-003 | Typo in footer text | Low | Look at footer | CLOSED |

## 5. Testing Checklist

### Backend
- [ ] All API endpoints return correct status codes (200, 201, 400, 404, 500)
- [ ] Request validation (invalid inputs rejected)
- [ ] Database operations (CRUD, relationships, integrity)
- [ ] Authentication & authorization
- [ ] Error handling & logging
- [ ] Performance (response time < 500ms)

### Frontend
- [ ] Components render correctly
- [ ] User interactions work (click, input, form submit)
- [ ] API integration (data fetched, displayed, errors handled)
- [ ] Form validation (invalid inputs highlighted)
- [ ] Responsive design (mobile, tablet, desktop)
- [ ] Accessibility (keyboard nav, ARIA labels, contrast)

### Integration
- [ ] Booking flow end-to-end
- [ ] Payment processing end-to-end
- [ ] Database migrations don't break existing data
- [ ] API contract between frontend & backend

## 6. Test Execution

```bash
# Backend tests
cd backend
pytest tests/ -v --cov=app

# Frontend tests
cd frontend
npm test -- --coverage

# Integration tests
npm run test:integration

# E2E tests (optional)
npx cypress run
```

## Key Principles
1. **Test critical paths:** Focus on requirements, happy path + edge cases
2. **Boundary testing:** API contracts must match exactly (request/response shapes)
3. **Incremental testing:** Test each module as completed, not wait for end
4. **Document findings:** Track bugs, provide reproduction steps
5. **Validate coverage:** Ensure all requirements have test coverage

## Tips
- Use fixtures/factories for test data
- Mock external APIs (payment gateway, email service)
- Test error scenarios (invalid input, API failure, DB failure)
- Keep tests focused (one assertion per test where possible)
- Use descriptive test names (describe what it tests)

