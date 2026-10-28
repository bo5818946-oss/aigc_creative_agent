import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import { usePageTitle } from "../lib/usePageTitle";

export function NotFoundPage() {
  usePageTitle("页面不存在");

  return (
    <div className="not-found">
      <p className="not-found-code">404</p>
      <h1 className="h1">这个页面不存在</h1>
      <p className="sub">
        地址可能已经改变，或者这条记录已经被删除。回到首页，或从项目列表继续。
      </p>
      <div className="not-found-actions">
        <Link to="/" className="btn btn-primary">
          <ArrowLeft size={15} strokeWidth={1.8} aria-hidden="true" />
          回到首页
        </Link>
        <Link to="/library" className="btn btn-secondary">
          查看项目
        </Link>
      </div>
    </div>
  );
}
