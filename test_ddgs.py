from ddgs import DDGS
with DDGS() as ddgs:
    try:
        results = ddgs.text("Kolkata weather", max_results=3)
        if results:
            for r in results:
                print(f"- {r.get('title')}: {r.get('body')}")
        else:
            print("No results")
    except Exception as e:
        print(e)
