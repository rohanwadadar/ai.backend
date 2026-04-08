from ddgs import DDGS
with DDGS() as ddgs:
    try:
        print("Testing default backend...")
        results = ddgs.text("Kolkata weather", max_results=3)
        print(results)
    except Exception as e:
        print(e)
    try:
        print("\nTesting lite backend...")
        results = ddgs.text("Kolkata weather", max_results=3, backend="lite")
        print(results)
    except Exception as e:
        print(e)
    try:
        print("\nTesting html backend...")
        results = ddgs.text("Kolkata weather", max_results=3, backend="html")
        print(results)
    except Exception as e:
        print(e)
