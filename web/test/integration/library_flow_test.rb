require "test_helper"
require "fileutils"
require "tmpdir"

# Walks the whole app the way a person does: claim an invite, add a library,
# browse the grid, open an item. Runs entirely against the bundled fixture
# library, so it needs no network and no credentials.
class LibraryFlowTest < ActionDispatch::IntegrationTest
  FIXTURE_LIBRARY = Rails.root.join("test/fixtures/library").to_s

  test "signup is closed without an invitation" do
    get "/invites/not-a-real-token"
    assert_redirected_to new_session_path
  end

  test "an expired invitation cannot be claimed" do
    invite = Invite.create!(expires_at: 1.day.ago)

    post "/invites/#{invite.token}", params: {
      email_address: "late@example.com", password: "password123",
      password_confirmation: "password123"
    }

    assert_redirected_to invite_path(invite.token)
    assert_nil User.find_by(email_address: "late@example.com")
  end

  test "an invitation can only be claimed once" do
    invite = Invite.create!
    claim(invite, "first@example.com")
    assert invite.reload.claimed?

    post "/invites/#{invite.token}", params: {
      email_address: "second@example.com", password: "password123",
      password_confirmation: "password123"
    }
    assert_nil User.find_by(email_address: "second@example.com")
  end

  test "full journey: claim an invite, add a library, browse it, open an item" do
    invite = Invite.create!
    claim(invite, "family@example.com")
    user = User.find_by!(email_address: "family@example.com")
    assert_equal user, invite.reload.claimed_by

    # No libraries yet.
    get "/libraries"
    assert_response :success

    post "/libraries", params: {
      label: "Fixtures", provider: "local", bucket: FIXTURE_LIBRARY,
      access_key_id: "not-used", secret_access_key: "not-used"
    }
    library = user.libraries.sole
    assert_redirected_to library_path(library)

    # The grid fetches and caches index.json on first view, so a viewer never
    # has to press Refresh to see anything at all.
    get library_path(library)
    assert_response :success
    assert_equal 5, library.reload.catalog.item_count

    item = library.catalog.items.find_by(path: "media/2026/piano-recital.mp4")
    get library_item_path(library, item)
    assert_response :success
  end

  test "credentials never reach the browser" do
    user = signed_in_user
    library = create_library(user)

    get edit_library_path(library)
    assert_response :success
    assert_no_match(/super-secret-value/, response.body,
      "the secret access key must never be serialised into a page")
    assert_match(/••••/, response.body, "the form should show a masked hint instead")
  end

  test "a blank secret on update keeps the stored one" do
    user = signed_in_user
    library = create_library(user)

    patch library_path(library), params: { label: "Renamed", secret_access_key: "" }

    library.reload
    assert_equal "Renamed", library.label
    assert_equal "super-secret-value", library.secret_access_key
  end

  test "Test connection checks the submitted values and saves nothing" do
    user = signed_in_user
    library = create_library(user)

    # It must test what is on screen, not the stored value...
    post verify_library_path(library), params: { label: "Only in the form" }
    assert_redirected_to edit_library_path(library)

    # ...and it must not persist it.
    assert_equal "Fixtures", library.reload.label
  end

  test "Test connection reports a bad directory without saving it" do
    user = signed_in_user
    library = create_library(user)

    post verify_library_path(library), params: { bucket: "/nowhere/at/all" }

    assert_equal LibraryFlowTest::FIXTURE_LIBRARY, library.reload.bucket
    follow_redirect!
    assert_flash :alert, /No directory/
  end

  test "one user cannot reach another user's library" do
    owner = signed_in_user("owner@example.com")
    library = create_library(owner)
    delete "/session"

    signed_in_user("intruder@example.com")
    get library_path(library)
    # 404, not 403: whether someone else's library exists is not this user's
    # business either way.
    assert_response :not_found
  end

  test "a bucket with no index.json explains itself instead of failing" do
    user = signed_in_user
    empty = Dir.mktmpdir
    library = user.libraries.create!(
      label: "Empty", provider: "local", bucket: empty,
      access_key_id: "x", secret_access_key: "y"
    )

    get library_path(library)
    assert_response :success
    assert inertia_props["catalogMissing"],
      "the page must be told the bucket has no catalog, so it can explain rather than show an empty grid"
  ensure
    FileUtils.remove_entry(empty) if empty
  end

  test "an endpoint pointing at a private address is refused" do
    user = signed_in_user

    library = user.libraries.build(
      label: "Evil", provider: "other", endpoint: "https://169.254.169.254",
      region: "us-east-1", bucket: "b", access_key_id: "x", secret_access_key: "y"
    )

    assert_not library.valid?
    assert_match(/private or reserved/, library.errors[:endpoint].join)
  end

  test "media is served with the type its extension names, and honours byte ranges" do
    user = signed_in_user
    library = create_library(user)
    get library_path(library) # populates the catalog

    key = "media/2026/piano-recital.mp4"
    get dev_media_path(library_id: library.id, key: key)
    assert_response :success
    # SPEC: the extension is authoritative for format. Nothing here opens the
    # file to find out what it is.
    assert_equal "video/mp4", response.media_type
    full_length = response.body.bytesize
    assert_equal "bytes", response.headers["Accept-Ranges"]

    # Seeking in a <video> is byte ranges and nothing else. An object store
    # answers these natively, so the local backend has to as well or seeking
    # works in production and breaks in development.
    get dev_media_path(library_id: library.id, key: key), headers: { "Range" => "bytes=0-999" }
    assert_response :partial_content
    assert_equal 1000, response.body.bytesize
    assert_equal "bytes 0-999/#{full_length}", response.headers["Content-Range"]

    get dev_media_path(library_id: library.id, key: key), headers: { "Range" => "bytes=-500" }
    assert_response :partial_content
    assert_equal 500, response.body.bytesize
  end

  test "a download link carries a content-disposition, since cross-origin download attributes are ignored" do
    user = signed_in_user
    library = create_library(user)
    get library_path(library)

    get dev_media_path(library_id: library.id, key: "media/2026/piano-recital.mp4", disposition: "attachment")
    assert_response :success
    assert_match(/attachment/, response.headers["Content-Disposition"])
    assert_match(/piano-recital\.mp4/, response.headers["Content-Disposition"])
  end

  test "the media route refuses a key that escapes the library root" do
    user = signed_in_user
    library = create_library(user)

    get dev_media_path(library_id: library.id, key: "../../../../etc/passwd")
    assert_response :not_found
  end

  test "write features are hidden on a read-only library, not merely refused" do
    user = signed_in_user
    library = create_library(user) # read_only by default

    # Not a 403: a read-only library should not advertise a door it cannot open.
    get library_sweep_path(library)
    assert_response :not_found

    post library_sweep_path(library)
    assert_response :not_found

    get library_path(library)
    assert_not inertia_props["library"]["writable"],
      "the page must know not to offer write features"
  end

  test "editing an item is refused on a read-only library" do
    user = signed_in_user
    library = create_library(user)
    get library_path(library)
    item = library.reload.catalog.items.first

    patch library_item_path(library, item), params: { title: "Should not stick" }
    assert_response :not_found
  end

  test "a writable library offers the sweep and can edit an item" do
    user = signed_in_user
    dir = Dir.mktmpdir
    FileUtils.cp_r(Rails.root.join("test/fixtures/library").to_s + "/.", dir)
    library = user.libraries.create!(
      label: "Writable", provider: "local", bucket: dir,
      access_key_id: "k", secret_access_key: "s", access_level: "read_write"
    )

    get library_path(library)
    assert inertia_props["library"]["writable"]

    get library_sweep_path(library)
    assert_response :success

    item = library.reload.catalog.items.find_by(path: "media/2026/untitled-clip.mp4")
    patch library_item_path(library, item), params: { title: "Named at last" }
    assert_redirected_to library_item_path(library, item)

    # Written through to the bucket, which is the source of truth...
    sidecar = JSON.parse(File.read(File.join(dir, "media/2026/untitled-clip.mp4.json")))
    assert_equal "Named at last", sidecar["title"]

    # ...reflected in the cached row...
    assert_equal "Named at last", item.reload.title

    # ...and amended in the catalog, so another client sees it too.
    index = JSON.parse(File.read(File.join(dir, "index.json")))
    entry = index["items"].find { |i| i["path"] == "media/2026/untitled-clip.mp4" }
    assert_equal "Named at last", entry["title"]
  ensure
    FileUtils.remove_entry(dir) if dir
  end

  private
    def claim(invite, email)
      post "/invites/#{invite.token}", params: {
        email_address: email, password: "password123", password_confirmation: "password123"
      }
    end

    def signed_in_user(email = "user@example.com")
      user = User.create!(email_address: email, password: "password123")
      post "/session", params: { email_address: email, password: "password123" }
      user
    end

    def create_library(user)
      user.libraries.create!(
        label: "Fixtures", provider: "local", bucket: FIXTURE_LIBRARY,
        access_key_id: "not-used", secret_access_key: "super-secret-value"
      )
    end
end
