def test_single_page_app_is_served(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"SupportDesk" in response.content
    assert b"frontend/app.js" in response.content
