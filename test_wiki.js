fetch("https://en.wikipedia.org/api/rest_v1/page/summary/Led_Zeppelin")
  .then(res => res.json())
  .then(data => console.log(data.extract))
