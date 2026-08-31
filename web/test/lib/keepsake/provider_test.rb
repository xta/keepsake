require "test_helper"

class Keepsake::ProviderTest < ActiveSupport::TestCase
  P = Keepsake::Provider

  test "a region is recovered from whatever form someone pastes" do
    # People paste what their provider's console shows them, which is usually
    # the endpoint, not the bare region.
    assert_equal "us-west-001", P.normalize_region("us-west-001")
    assert_equal "us-west-001", P.normalize_region("s3.us-west-001")
    assert_equal "us-west-001", P.normalize_region("s3.us-west-001.backblazeb2.com")
    assert_equal "us-west-001", P.normalize_region("https://s3.us-west-001.backblazeb2.com")
    assert_equal "us-west-001", P.normalize_region("  US-West-001  ")
  end

  test "presets build their own endpoints" do
    assert_equal "https://s3.us-east-1.amazonaws.com", P.endpoint_for("aws", region: "us-east-1")
    assert_equal "https://s3.us-west-001.backblazeb2.com", P.endpoint_for("b2", region: "us-west-001")
    assert_equal "https://acc.r2.cloudflarestorage.com", P.endpoint_for("r2", region: nil, account_id: "acc")
  end

  test "r2 signs with a region even though it has none" do
    assert_equal "auto", P.region_for("r2", region: nil)
  end

  test "the local provider is not offered in production" do
    assert_includes P.selectable, "local"
    assert_not_includes P::PUBLIC_NAMES, "local"
  end
end
