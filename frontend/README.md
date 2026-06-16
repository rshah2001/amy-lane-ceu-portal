# CEU Compliance Flutter Web Client

## Prerequisites

- Flutter stable with web support enabled
- Backend running at `http://localhost:8000`
- For image uploads, the backend machine needs Tesseract OCR installed.

## Run

```bash
cd frontend
flutter pub get
flutter run -d chrome --web-port 8080 --dart-define=API_BASE_URL=http://localhost:8000/api
```

## Production Build

```bash
flutter build web --release --dart-define=API_BASE_URL=https://api.example.com/api
```

The generated static site is under `build/web`.
