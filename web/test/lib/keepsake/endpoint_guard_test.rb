require "test_helper"

class Keepsake::EndpointGuardTest < ActiveSupport::TestCase
  G = Keepsake::EndpointGuard

  test "refuses anything but https" do
    assert_not G.safe?("http://s3.us-east-005.backblazeb2.com")
    assert_not G.safe?("file:///etc/passwd")
    assert_not G.safe?("ftp://example.com")
  end

  test "refuses addresses this server should never be aimed at" do
    # The cloud metadata endpoint is the whole reason this guard exists.
    assert_not G.safe?("https://169.254.169.254/")
    assert_not G.safe?("https://127.0.0.1/")
    assert_not G.safe?("https://10.0.0.5/")
    assert_not G.safe?("https://192.168.1.1/")
    assert_not G.safe?("https://172.16.0.1/")
  end

  test "refuses IPv6 loopback and ipv4-mapped addresses" do
    assert_not G.safe?("https://[::1]/")
    # Without the mapped-address check this bypass is trivial.
    assert_not G.safe?("https://[::ffff:127.0.0.1]/")
  end

  test "allows a real provider endpoint" do
    assert G.safe?("https://s3.us-east-005.backblazeb2.com")
  end

  test "the rejection message says why" do
    error = assert_raises(G::Rejected) { G.validate!("https://127.0.0.1") }
    assert_match(/private or reserved/, error.message)
  end
end
