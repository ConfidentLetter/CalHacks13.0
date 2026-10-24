from eval import truth as T


def test_label_page_served(client):
    r = client.get("/label")
    assert r.status_code == 200 and "Label" in r.text and "katex" in r.text


def test_pages_listing_and_prelabel_roundtrip(client, testset):
    pages = client.get("/label/api/pages").json()["pages"]
    assert [p["name"] for p in pages] == ["1", "2"] and not pages[0]["has_truth"]
    r = client.post("/label/api/page/1/prelabel?mock=1")
    assert r.status_code == 200, r.text
    assert r.json()["summary"]["lines"] == 4
    page = client.get("/label/api/page/1").json()
    assert page["truth"]["lines"][2]["status"] == "crossed_out"
    assert page["image_url"].startswith("/files/")


def test_save_truth_validates_and_persists(client, testset, mock_truth):
    mock_truth["lines"][1]["planted_error"] = True
    mock_truth["lines"][1]["corrected_latex"] = "f'(x)=2x\\sin x+x^{2}\\cos x"
    mock_truth["lines"][1]["planted_note"] = "product rule: dropped x^2 cos x"
    mock_truth["reviewed"] = True
    r = client.post("/label/api/page/1", json={"truth": mock_truth})
    assert r.status_code == 200, r.text
    assert r.json()["summary"] == {"name": "1", "has_truth": True, "reviewed": True, "lines": 4, "planted": 1}
    assert T.load_truth("1", testset)["lines"][1]["planted_note"].startswith("product rule")
    # reviewed pages are protected from re-prelabel
    assert client.post("/label/api/page/1/prelabel?mock=1&force=1").status_code == 409


def test_save_rejects_invalid(client, mock_truth):
    mock_truth["lines"][0]["status"] = "nope"
    r = client.post("/label/api/page/1", json={"truth": mock_truth})
    assert r.status_code == 422 and "status" in r.json()["details"][0]


def test_unknown_page_404(client):
    assert client.get("/label/api/page/nope").status_code == 404
    assert client.get("/label/api/page/..%2Fx").status_code in (400, 404)
