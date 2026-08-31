require "test_helper"
require "fileutils"
require "tmpdir"

# The write path. Everything here runs against a throwaway copy of the fixture
# library, so the committed fixtures are never mutated.
class Keepsake::SweepTest < ActiveSupport::TestCase
  setup do
    @user = User.create!(email_address: "sweep@example.com", password: "password123")
    @dir = Dir.mktmpdir
    FileUtils.cp_r(Rails.root.join("test/fixtures/library").to_s + "/.", @dir)
    @library = build_library(access_level: "read_write")
  end

  teardown { FileUtils.remove_entry(@dir) if @dir }

  test "a plan finds media that arrived without metadata" do
    add_media("media/2026/from-my-phone.mp4")

    plan = Keepsake::Sweep.new(@library).plan

    assert_equal [ "media/2026/from-my-phone.mp4" ], plan[:adoptable].map { |f| f[:path] }
    assert_equal 5, plan[:already_indexed]
  end

  test "adopting writes a spec-valid sidecar and invents nothing" do
    add_media("media/2026/from-my-phone.mp4")

    Keepsake::Sweep.new(@library).apply
    sidecar = JSON.parse(File.read(File.join(@dir, "media/2026/from-my-phone.mp4.json")))

    # SPEC's four required fields, all machine-generated.
    assert_equal 1, sidecar["schema"]
    assert sidecar["id"].present?
    assert_equal "from-my-phone.mp4", sidecar["file"]
    assert_match(/\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\z/, sidecar["uploaded_at"])

    # Known from the bucket, so recorded.
    assert_equal "video/mp4", sidecar["media_type"]
    assert sidecar["size_bytes"].positive?

    # ABSENT, not placeholdered. Inventing a title or a date would put a fact
    # in the archive that nobody established.
    assert_not sidecar.key?("title")
    assert_not sidecar.key?("recorded_at")
  end

  test "adopting never overwrites an existing sidecar" do
    original = File.read(File.join(@dir, "media/2026/piano-recital.mp4.json"))

    Keepsake::Sweep.new(@library).apply

    assert_equal original, File.read(File.join(@dir, "media/2026/piano-recital.mp4.json")),
      "an existing sidecar is the source of truth and must not be rewritten"
  end

  test "adopting leaves the media files alone" do
    add_media("media/2026/from-my-phone.mp4")
    before = media_digests

    Keepsake::Sweep.new(@library).apply

    # Byte-for-byte identical. A sweep only ever adds .json files.
    assert_equal before, media_digests
  end

  test "a read-only library refuses to write" do
    read_only = build_library(access_level: "read_only", label: "Read only")
    add_media("media/2026/from-my-phone.mp4")

    assert_raises(Keepsake::Sweep::ReadOnly) { Keepsake::Sweep.new(read_only).apply }
    assert_not File.exist?(File.join(@dir, "media/2026/from-my-phone.mp4.json"))
  end

  test "the rebuilt catalog is sorted by path and inlines each sidecar" do
    add_media("media/2026/aaa-first.mp4")
    Keepsake::Sweep.new(@library).apply

    index = JSON.parse(File.read(File.join(@dir, "index.json")))

    assert_equal 6, index["count"]
    assert_equal index["items"].map { |i| i["path"] }.sort, index["items"].map { |i| i["path"] },
      "SPEC makes ascending path order a stability guarantee"

    piano = index["items"].find { |i| i["path"] == "media/2026/piano-recital.mp4" }
    assert_equal "Spring Recital", piano["title"], "the whole sidecar is inlined, not referenced"
  end

  test "problems are reported rather than raised" do
    File.write(File.join(@dir, "media/2026/orphan.mp4.json"), "{}")
    FileUtils.mkdir_p(File.join(@dir, "media/2026"))
    File.write(File.join(@dir, "media/2026/README"), "no extension")

    problems = Keepsake::Sweep.new(@library).plan[:problems]
    kinds = problems.map { |p| p[:kind] }

    assert_includes kinds, "sidecar_without_media"
    assert_includes kinds, "no_extension"
  end

  private
    # Every non-JSON file, by content. Directories are excluded: their size
    # changes when a file is added to them, which says nothing about the media.
    def media_digests
      Dir.glob(File.join(@dir, "**/*"))
        .select { |f| File.file?(f) && !f.end_with?(".json") }
        .to_h { |f| [ f.delete_prefix(@dir), Digest::SHA256.file(f).hexdigest ] }
    end

    def build_library(access_level:, label: "Sweepable")
      @user.libraries.create!(
        label: label, provider: "local", bucket: @dir,
        access_key_id: "k", secret_access_key: "s", access_level: access_level
      )
    end

    def add_media(key)
      path = File.join(@dir, key)
      FileUtils.mkdir_p(File.dirname(path))
      FileUtils.cp(Rails.root.join("test/fixtures/library/media/2026/piano-recital.mp4"), path)
    end
end
