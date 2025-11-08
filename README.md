# StreamHost Deployment Guide

This guide walks through setting up the full environment for StreamHost, including
system packages, Python dependencies, database services, configuration, and day-to-day
operations.

## 1. Install System Dependencies

> **Note:** The commands below target Ubuntu/Debian systems. Adjust the package
> names as needed for other distributions.

```bash
# Update the system
sudo apt update && sudo apt upgrade -y

# Install FFmpeg with necessary codecs
sudo apt install -y ffmpeg

# Verify FFmpeg installation
ffmpeg -version
ffmpeg -encoders | grep h264
ffmpeg -encoders | grep aac

# Install Python 3.11+
sudo apt install -y python3.11 python3.11-venv python3-pip

# Install PostgreSQL
sudo apt install -y postgresql postgresql-contrib

# Install Redis
sudo apt install -y redis-server

# Install additional utilities
sudo apt install -y git curl wget nginx
```

### Hardware Acceleration (Optional)

```bash
# NVIDIA GPU (NVENC)
sudo apt install -y nvidia-driver-535 nvidia-cuda-toolkit

# Intel QuickSync
sudo apt install -y intel-media-va-driver-non-free
```

## 2. Create a Python Virtual Environment

```bash
# Create virtual environment
python3.11 -m venv venv

# Activate virtual environment
source venv/bin/activate

# Upgrade packaging tools
pip install --upgrade pip setuptools wheel
```

## 3. Install Python Dependencies

```bash
pip install -r requirements.txt
```

## 4. Set Up the Database

```bash
# Start PostgreSQL
sudo systemctl start postgresql
sudo systemctl enable postgresql

# Create database and user
export POSTGRES_PASSWORD="$(openssl rand -base64 18)"
sudo -u postgres psql <<'EOF'
CREATE DATABASE moviestream;
CREATE USER streamadmin WITH PASSWORD '${POSTGRES_PASSWORD}';
GRANT ALL PRIVILEGES ON DATABASE moviestream TO streamadmin;
\q
EOF

# Run migrations
python manage.py migrate
```

## 5. Configure Redis

```bash
# Start Redis
sudo systemctl start redis-server
sudo systemctl enable redis-server

# Test Redis
redis-cli ping  # Should return PONG
```

## 6. Application Configuration

### Environment Variables

1. Copy the example environment file and edit the resulting `.env` file.

   ```bash
   cp .env.example .env
   nano .env
   ```

2. Fill in the following template values:

   ```ini
   # Application
   APP_ENV=production
   DEBUG=False
   SECRET_KEY=your_super_secure_secret_key_here

   # YouTube Configuration
   YOUTUBE_STREAM_KEY=xxxx-xxxx-xxxx-xxxx-xxxx
   YOUTUBE_RTMP_URL=rtmp://a.rtmp.youtube.com/live2

   # YouTube API (for metadata updates)
   YOUTUBE_CLIENT_ID=your_client_id.apps.googleusercontent.com
   YOUTUBE_CLIENT_SECRET=your_client_secret
   YOUTUBE_REFRESH_TOKEN=your_refresh_token

   # Database
DATABASE_URL=postgresql://streamadmin:${POSTGRES_PASSWORD}@localhost:5432/moviestream

   # Redis
   REDIS_URL=redis://localhost:6379/0

   # Paths
   MOVIES_DIR=/mnt/movies
   CACHE_DIR=/var/cache/moviestream
   LOGS_DIR=/var/log/moviestream

   # Stream Settings
   STREAM_RESOLUTION=1920x1080
   STREAM_BITRATE=4000k
   STREAM_FPS=30
   STREAM_PRESET=fast
   HARDWARE_ACCEL=false  # Set to 'nvenc' or 'qsv' if available

   # Monitoring
   SENTRY_DSN=https://your_sentry_dsn@sentry.io/project_id
   PROMETHEUS_PORT=9090

   # Alerts
   ALERT_EMAIL=admin@example.com
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USER=your_email@gmail.com
   SMTP_PASSWORD=your_app_password

   # Slack/Discord Webhooks (optional)
   SLACK_WEBHOOK_URL=https://hooks.slack.com/services/YOUR/WEBHOOK/URL
   DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/YOUR_WEBHOOK

   # Security
   ALLOWED_HOSTS=localhost,yourdomain.com
   CORS_ORIGINS=https://yourdomain.com
   JWT_SECRET=your_jwt_secret_key

   # Admin Account
   ADMIN_USERNAME=admin
   ADMIN_PASSWORD=change_this_password
   ADMIN_EMAIL=admin@example.com
   ```

### Stream Profiles

Edit `config/stream_profiles.yaml` to adjust stream settings and hardware acceleration
options.

```yaml
profiles:
  default:
    resolution: "1920x1080"
    bitrate: "4000k"
    fps: 30
    preset: "fast"
    audio_bitrate: "128k"
    audio_sample_rate: 44100

  high_quality:
    resolution: "1920x1080"
    bitrate: "6000k"
    fps: 60
    preset: "slow"
    audio_bitrate: "192k"
    audio_sample_rate: 48000

  low_bandwidth:
    resolution: "1280x720"
    bitrate: "2500k"
    fps: 30
    preset: "veryfast"
    audio_bitrate: "96k"
    audio_sample_rate: 44100

hardware_acceleration:
  nvenc:
    encoder: "h264_nvenc"
    preset: "p4"
    profile: "high"

  qsv:
    encoder: "h264_qsv"
    preset: "medium"
    profile: "high"
```

### Playlist Rules

Edit `config/playlist_rules.yaml` to control content scheduling and genre rotation.

```yaml
playlist_settings:
  min_gap_between_repeats: 168  # Hours (7 days)
  max_consecutive_same_genre: 2
  enable_shuffle: true
  enable_scheduled_content: true

genres:
  - action
  - comedy
  - drama
  - thriller
  - sci-fi
  - documentary

scheduled_events:
  - name: "Weekend Blockbusters"
    day: "saturday"
    time: "20:00"
    genre: "action"

  - name: "Sunday Night Classics"
    day: "sunday"
    time: "21:00"
    duration: 120  # minutes minimum
```

## 7. Running StreamHost

### Manual Start

```bash
source venv/bin/activate
uvicorn app.main:app --reload
```

### Systemd Service (Production)

```bash
sudo systemctl start moviestream
sudo systemctl status moviestream
sudo journalctl -u moviestream -f
```

### Docker Workflow

```bash
docker compose up --build -d
docker compose logs -f app
docker compose down
```

## 8. Managing the Movie Library

### Add Movies

```bash
python manage.py add-movie /path/to/movie.mp4 \
  --title "Movie Title" \
  --genre action \
  --duration 7200

python manage.py scan-directory /mnt/movies \
  --auto-detect-metadata
```

### Generate Playlists

```bash
python manage.py generate-playlist --hours 24

python manage.py generate-playlist \
  --strategy genre-balanced \
  --hours 48
```

## 9. Web Dashboard and API

The FastAPI service renders the management dashboard at `http://localhost:8000/`. The
navigation pages are now backed by live endpoints and enforce CSRF protection and
rate limiting for all state-changing operations.

### API Examples

- Health probe:

  ```bash
  curl http://localhost:8000/api/v1/stream/health
  ```

- Stream telemetry:

  ```bash
  curl http://localhost:8000/api/v1/stream/status
  ```

- Playlist management (requires a CSRF token issued via the browser session):

  ```bash
  curl -X POST http://localhost:8000/api/v1/playlist \
    -H "X-CSRF-Token: YOUR_SESSION_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{"title": "Sample", "genre": "drama", "duration_seconds": 3600}'
  ```

- Media ingestion with validation:

  ```bash
  curl -X POST http://localhost:8000/api/v1/media/upload \
    -H "X-CSRF-Token: YOUR_SESSION_TOKEN" \
    -F "title=Sample" \
    -F "genre=action" \
    -F "duration_seconds=4200" \
    -F "file=@movie.mp4"
  ```

## 10. Project Structure Overview

```
streamhost/
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes/
│   │       ├── media.py
│   │       ├── playlist.py
│   │       ├── stream.py
│   │       └── system.py
│   ├── core/
│   │   ├── auth.py
│   │   ├── config.py
│   │   ├── logging_config.py
│   │   └── security.py
│   ├── db/
│   │   ├── base.py
│   │   ├── init_db.py
│   │   └── session.py
│   ├── models/
│   │   └── __init__.py
│   ├── schemas.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── media_service.py
│   │   ├── playlist_service.py
│   │   ├── settings_service.py
│   │   ├── stream_manager.py
│   │   └── video_processor.py
│   └── web/
│       ├── __init__.py
│       ├── routes.py
│       ├── static/
│       │   ├── css/
│       │   │   └── style.css
│       │   └── js/
│       │       └── app.js
│       └── templates/
│           ├── base.html
│           ├── home.html
│           ├── media.html
│           ├── playlist.html
│           └── settings.html
├── data/
│   └── .gitkeep
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

## 11. Containerized Deployment

StreamHost includes a production-ready Dockerfile and `docker-compose.yml` to
launch the application alongside PostgreSQL and Redis with a single command.

### Build and Run with Docker Compose

1. Ensure you have a `.env` file populated with the settings described earlier in
   this guide.
2. Build and start the stack:

   ```bash
   docker compose up --build
   ```

   This will build the StreamHost image, start PostgreSQL and Redis, and expose
   the web interface on <http://localhost:8000>.

3. Stop the stack when you're done:

   ```bash
   docker compose down
   ```

   Add the `-v` flag if you want to remove the PostgreSQL and Redis volumes.

### Customizing the Services

- Override the default command or environment variables in
  `docker-compose.yml` to adapt the stack to your infrastructure.
- Mount additional host directories into `/app/data` if you want the container
  to access an existing movie library.
- Update the PostgreSQL credentials in `docker-compose.yml` (and the matching
  `DATABASE_URL` in `.env`) before deploying to production.

## 12. API Reference Summary

All JSON endpoints (except `/stream/health`) require a Bearer token obtained via
the OAuth2 password flow. Use the default `admin` account (or one you create)
to request a token and include the returned `Authorization: Bearer` header in
subsequent calls. State-changing requests additionally expect a CSRF token in
`X-CSRF-Token`.

| Method | Endpoint                        | Description                              |
| ------ | ------------------------------- | ---------------------------------------- |
| POST   | `/api/v1/auth/token`            | Obtain a JWT access token                 |
| GET    | `/api/v1/auth/me`               | Inspect the authenticated user            |
| GET    | `/api/v1/stream/status`         | Retrieve stream telemetry (auth required) |
| POST   | `/api/v1/stream/start`          | Launch streaming for a media ID          |
| POST   | `/api/v1/stream/stop`           | Terminate the running stream             |
| GET    | `/api/v1/stream/health`         | Lightweight liveness probe               |
| GET    | `/api/v1/playlist`              | Upcoming playlist items                  |
| POST   | `/api/v1/playlist`              | Append an item (auth + CSRF)             |
| DELETE | `/api/v1/playlist/{id}`         | Remove an entry (auth + CSRF)            |
| GET    | `/api/v1/media`                 | List uploaded media                      |
| POST   | `/api/v1/media/upload`          | Upload media (auth + CSRF)               |
| GET    | `/api/v1/system/settings`       | Retrieve persisted settings              |
| PUT    | `/api/v1/system/settings`       | Update settings (auth + CSRF)            |
Full interactive documentation is available at `http://localhost:8000/docs` (Swagger UI).
