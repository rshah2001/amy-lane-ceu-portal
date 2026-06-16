FROM ghcr.io/cirruslabs/flutter:stable AS build

ARG API_BASE_URL=http://localhost:8000/api
WORKDIR /app
COPY pubspec.yaml analysis_options.yaml ./
RUN flutter pub get
COPY . .
RUN flutter build web --release --dart-define=API_BASE_URL=${API_BASE_URL}

FROM nginx:1.27-alpine
COPY --from=build /app/build/web /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80

