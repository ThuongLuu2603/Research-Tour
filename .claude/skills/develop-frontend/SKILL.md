---
name: develop-frontend
description: Phát triển frontend UI/UX cho OTA platform - implement React components, pages, API integration. Dùng khi cần phát triển UI, state management, API clients.
---

# Develop Frontend Skill

## Mục đích
Implement React UI/UX, components, pages, state management, API integration cho OTA platform.

## Project Structure
```
frontend/src/
├── components/          # Reusable React components
│   ├── Header.tsx
│   ├── Footer.tsx
│   ├── TourCard.tsx
│   ├── BookingForm.tsx
│   └── [other components]
├── pages/              # Page components (routing)
│   ├── HomePage.tsx
│   ├── ToursPage.tsx
│   ├── BookingPage.tsx
│   ├── ProfilePage.tsx
│   └── [other pages]
├── lib/                # Utilities & helpers
│   ├── api.ts          # API client
│   ├── hooks.ts        # Custom hooks
│   └── utils.ts        # Helper functions
├── contexts/           # React contexts (state management)
│   ├── AuthContext.tsx
│   ├── CartContext.tsx
│   └── [other contexts]
├── App.tsx             # Main App component
├── main.tsx            # Entry point
└── index.css           # Global styles
```

## Workflow

### 1. Component Development (React + TypeScript)
```typescript
// components/TourCard.tsx
interface TourCardProps {
  tour: Tour;
  onBook: (tourId: string) => void;
}

export const TourCard: React.FC<TourCardProps> = ({ tour, onBook }) => {
  return (
    <div className="tour-card">
      <h3>{tour.title}</h3>
      <p>{tour.destination}</p>
      <p>Price: ${tour.basePrice}</p>
      <button onClick={() => onBook(tour.id)}>Book Now</button>
    </div>
  );
};
```

### 2. Page Components (Routing)
```typescript
// pages/ToursPage.tsx
import { useState, useEffect } from "react";
import { TourCard } from "../components/TourCard";
import { getTours } from "../lib/api";

export const ToursPage: React.FC = () => {
  const [tours, setTours] = useState<Tour[]>([]);
  const [destination, setDestination] = useState("");

  useEffect(() => {
    getTours({ destination }).then(setTours);
  }, [destination]);

  return (
    <div>
      <input
        placeholder="Search destination"
        onChange={(e) => setDestination(e.target.value)}
      />
      <div className="tours-grid">
        {tours.map((tour) => (
          <TourCard key={tour.id} tour={tour} onBook={handleBook} />
        ))}
      </div>
    </div>
  );
};
```

### 3. API Client (Type-safe)
```typescript
// lib/api.ts
const API_BASE = process.env.REACT_APP_API_URL || "http://localhost:8000/api";

export async function getTours(params?: GetToursParams): Promise<Tour[]> {
  const query = new URLSearchParams();
  if (params?.destination) query.set("destination", params.destination);
  if (params?.category) query.set("category", params.category);
  
  const response = await fetch(`${API_BASE}/tours?${query}`);
  if (!response.ok) throw new Error("Failed to fetch tours");
  return response.json();
}

export async function createBooking(data: BookingCreate): Promise<Booking> {
  const response = await fetch(`${API_BASE}/bookings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!response.ok) throw new Error("Booking failed");
  return response.json();
}
```

### 4. State Management (Context + Hooks)
```typescript
// contexts/CartContext.tsx
interface CartContextType {
  items: CartItem[];
  addItem: (tour: Tour, passengers: number) => void;
  removeItem: (tourId: string) => void;
  clearCart: () => void;
}

const CartContext = createContext<CartContextType | undefined>(undefined);

export function CartProvider({ children }: { children: React.ReactNode }) {
  const [items, setItems] = useState<CartItem[]>([]);

  const addItem = (tour: Tour, passengers: number) => {
    setItems([...items, { tour, passengers, id: tour.id }]);
  };

  const removeItem = (tourId: string) => {
    setItems(items.filter(item => item.id !== tourId));
  };

  return (
    <CartContext.Provider value={{ items, addItem, removeItem, clearCart }}>
      {children}
    </CartContext.Provider>
  );
}

export function useCart() {
  const ctx = useContext(CartContext);
  if (!ctx) throw new Error("useCart must be used within CartProvider");
  return ctx;
}
```

### 5. Form Handling & Validation
```typescript
// pages/BookingPage.tsx
import { useForm } from "react-hook-form";
import { bookingSchema } from "../lib/schemas";

export const BookingPage: React.FC = () => {
  const { register, handleSubmit, formState: { errors } } = useForm({
    resolver: zodResolver(bookingSchema),
  });

  const onSubmit = async (data: BookingCreate) => {
    try {
      const booking = await createBooking(data);
      // Navigate to confirmation
    } catch (error) {
      // Show error message
    }
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)}>
      <input {...register("email")} placeholder="Email" />
      {errors.email && <span>{errors.email.message}</span>}
      
      <input {...register("passengers")} type="number" />
      {errors.passengers && <span>{errors.passengers.message}</span>}
      
      <button type="submit">Book Now</button>
    </form>
  );
};
```

### 6. Responsive Design
```css
/* index.css */
@media (max-width: 768px) {
  .tours-grid {
    grid-template-columns: 1fr;
  }
  
  .tour-card {
    padding: 1rem;
  }
}
```

## Component Patterns

| Pattern | Use Case | Example |
|---------|----------|---------|
| **Container/Presentational** | Separate logic from UI | ToursPageContainer / TourCard |
| **Custom Hooks** | Reusable logic | useTours(), useBooking() |
| **Context** | Global state | Auth, Cart, Notifications |
| **Error Boundary** | Error handling | <ErrorBoundary> |
| **Suspense** | Async loading | <Suspense fallback={<Loader />}> |
| **Portal** | Modals/overlays | <Portal><Modal /></Portal> |

## Performance Tips
- Code splitting: `lazy()` & `Suspense` for routes
- Memoization: `memo()` for expensive components
- Image optimization: Use `<img loading="lazy">` or CDN
- Bundle analysis: Check bundle size
- CSS-in-JS: Consider performance impact (styled-components, Tailwind)

## Accessibility (WCAG 2.1 AA)
- Semantic HTML: Use `<button>`, `<input>`, `<nav>`
- ARIA labels: `aria-label`, `aria-describedby`
- Keyboard navigation: Tab order, focus management
- Color contrast: WCAG AA minimum (4.5:1)
- Alt text: For all images

## Testing
```typescript
// components/TourCard.test.tsx
import { render, screen } from "@testing-library/react";
import { TourCard } from "./TourCard";

test("renders tour card with title", () => {
  const tour = { id: "1", title: "Paris Tour", ... };
  render(<TourCard tour={tour} onBook={jest.fn()} />);
  
  expect(screen.getByText("Paris Tour")).toBeInTheDocument();
});
```

## Code Style
- Use TypeScript for type safety
- Follow React best practices (hooks, functional components)
- Use ESLint & Prettier for formatting
- Write descriptive component/variable names
- Document complex components with JSDoc comments

