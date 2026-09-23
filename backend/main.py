from app.main import app


@app.get("/health")
def health():
	return {
		"status": "ok"
	}
