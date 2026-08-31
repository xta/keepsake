module InertiaTestHelper
  # Inertia embeds its page object as JSON in the layout. Assertions about what
  # a page was told therefore read props, not markup -- the wording itself
  # lives in the Vue component and is never server-rendered.
  def inertia_page
    json = response.body[/<script data-page="app" type="application\/json">(.*?)<\/script>/m, 1]
    raise "no Inertia page object in this response" if json.nil?
    JSON.parse(CGI.unescapeHTML(json))
  end

  def inertia_props = inertia_page["props"]

  def assert_flash(kind, pattern)
    actual = inertia_props.dig("flash", kind.to_s)
    assert_match pattern, actual.to_s,
      "expected the #{kind} flash to match #{pattern.inspect}, got #{actual.inspect}"
  end
end
