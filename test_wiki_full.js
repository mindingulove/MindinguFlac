fetch("https://en.wikipedia.org/w/api.php?action=query&prop=extracts&exintro=false&explaintext=true&titles=Led_Zeppelin&format=json")
  .then(res => res.json())
  .then(data => {
    const pages = data.query.pages;
    const pageId = Object.keys(pages)[0];
    console.log(pages[pageId].extract.substring(0, 500));
  });
